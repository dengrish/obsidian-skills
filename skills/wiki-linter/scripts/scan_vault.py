#!/usr/bin/env python3
"""Whole-vault scanner for the wiki-linter skill — Step 0, "Inventory the vault".

Parses every `Wiki/**/*.md` entry once (recursively, like wiki-builder's
vault_index.py) and emits a single JSON object: the vault inventory, the
deterministic QC violations ("problems"), and the three worklists the model must
judge — collision candidates (item-5 probes), rename candidates, and backfill
candidates (Task 2) — plus the Task 3 hierarchy diagnostic.

A file that cannot be read (not UTF-8, dangling symlink, permission error) is
reported as an `item0` problem and skipped; it never aborts the scan.

The scanner is a FLOOR, not a ceiling. It mechanizes every check that is
deterministic; every judgment call stays the model's. Nothing here is applied to
the vault: the candidate lists are worklists, not auto-fixes. See
references/scanner.md for the field-by-field output contract and for what the
scanner deliberately does not check.

Stdlib only, Python 3.8+.

    python3 scripts/scan_vault.py /path/to/vault/Wiki \
        --images /path/to/vault/Sources/Images \
        --out '/tmp/wiki-scan-<run-id>.json'

`--images` is optional and turns on one check: that every `![[…png]]` embed
names a file that is actually in `Sources/Images/`.  CONVENTIONS.md §1 makes
this skill that folder's embed validator, and without the argument there was no
path from here to the folder at all.
"""

import argparse
import datetime
import json
import os
import re
import sys
import unicodedata


def fold_name(s):
    """Case- and Unicode-normalization-folded key for a slug or link target.

    This is how the documented vault actually resolves two names to one file:
    Obsidian matches wikilinks case-insensitively, and the vault lives on APFS,
    which is case-insensitive AND normalization-insensitive (an NFC name and
    its NFD spelling open the same file).  Every comparison that answers "do
    these two names denote one file?" goes through this; comparing the raw
    strings instead is only correct on the case-sensitive Linux filesystems
    the plugin is tested on, which is exactly why the bug never showed there.
    """
    return unicodedata.normalize("NFC", s or "").casefold()


# Disciplines are the fixed 27-tag enum (VALID_TAGS below), not self-rooted notes — wiki-builder
# replaced roots: (a wikilink to a discipline note) with tags: (#-prefixed discipline slugs). See below.

# ===========================================================================
# NO SLUG IMPLEMENTATION LIVES HERE.  There is exactly one copy of the
# algorithm -- shared/scripts/slugify.py -- reached through the canonical
# bootstrap below (shared/CONVENTIONS.md §5).  A vendored copy used to sit in
# this spot, kept in sync by hand.
#
# Do NOT paste one back.  Drift is destructive, not cosmetic: the scanner
# proposes vault-wide renames from slug(), so a slug computed differently here
# from the one that named the file turns every correctly-named entry into a
# false rename candidate -- and two titles that collapse to one slug here (C++
# and C# both to "c") propose two renames onto the same destination, the second
# silently clobbering the first.
# `python3 shared/scripts/slugify.py --test` is the conformance suite.
# ===========================================================================

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

from slugify import SlugError as _SlugError, slug_stem as _slug_stem  # noqa: E402
from yaml_scalars import parse_scalar, strip_comment  # noqa: E402

# ===========================================================================
# NO SINGULARIZER LIVES HERE EITHER, and for the same reason.  The item-5
# `plural` and `word-order-singular` probes turn on which two word forms are
# the same word; wiki-builder's find_collisions.py probes (c) and (e) turn on
# the same fact.  This file used to carry a three-rule regular-plural stripper
# of its own, which answered "hypotheses" with "hypothes" where wiki-builder
# answered "hypothesis" -- so `hypothesis-testing` / `testing-hypotheses` was
# caught when wiki-builder probed a NEW candidate against the vault and missed
# by the sweep here.  CONVENTIONS.md §9 gives whole-vault dedup detection to
# this skill alone, so a pair already sitting in the vault was reported by
# nobody at all.  `python3 shared/scripts/plurals.py --test` is the
# conformance suite.  Do NOT paste a copy back.
# ===========================================================================
from plurals import (  # noqa: E402
    pluralize, real_permutation, singular_key, singular_keys,
    wordorder_key_singular,
)


def slug(title):
    """Slug stem for ``title``; "" when the title reduces to the empty slug.

    A thin wrapper over the canonical ``slugify.slug_stem``, which raises
    ``SlugError`` where this file's callers expect "".  An empty return means
    the title cannot be slugged automatically (a CJK/all-symbol title).
    Callers must NOT treat "" as a filename: renaming an entry to "" produces
    a file literally called ".md".
    """
    if not title:
        return ""
    try:
        return _slug_stem(str(title))
    except _SlugError:
        return ""


COMMON_NOUNS = {"regression","classification","clustering","inertia","entropy","policy",
 "return","transformer","kernel","filter","bias","gradient","tensor","attention","model",
 "vector","domain","field","function","label","shrinkage"}

# libraries used in item-6 API-surface failure-string scan
LIBS = ["PyTorch","TensorFlow","JAX","NumPy","Pandas","scikit-learn","sklearn","Keras",
        "SciPy","Matplotlib","Hugging Face","XGBoost","LightGBM","CatBoost"]

def leftover_dollars(body):
    # `strip_fenced`, not a backtick-only regex: markdown fences a block with
    # ``` OR ~~~, `strip_fenced` has always understood both, and this scan
    # understood only the first — so a `~~~` shell listing containing `$HOME`
    # was counted, and item 12's class-1 remediation writes `\$` into the
    # middle of the listing, corrupting the command it shows.
    s = strip_fenced(body)                            # fenced code (``` and ~~~)
    s = re.sub(r"`[^`]*`", " ", s)                    # inline code
    s = s.replace(r"\$", " ")                          # escaped \$
    s = re.sub(r"\$\$.*?\$\$", " ", s, flags=re.S)    # display math
    s = re.sub(r"\$[^$\n]*\$", " ", s)               # inline math
    return s.count("$")                               # leftover literal $

REMOTE_IMG = re.compile(r"!\[[^\]]*\]\((https?://[^)]+)\)")
# a standalone image-embed line (Obsidian ![[…png]] or markdown ![](url)) — for the caption check
EMB = re.compile(r"^\s*(?:!\[\[[^\]]*\.(?:png|jpe?g|gif|svg|webp|tiff?|bmp|avif)(?:\|[^\]]*)?\]\]|!\[[^\]]*\]\([^)]*\))\s*$", re.I)
#: An Obsidian image EMBED and the filename it names, anywhere on a line:
#: `![[Doe_X_2025_fig_3.png]]`, with an optional `|width` display pipe. This is
#: the `--images` existence check's reader. Markdown `![](…)` embeds are
#: deliberately NOT here: a remote one is `item12/remote-image` (report-only,
#: and the form wiki-builder mandates for a URL), and a local one is not a form
#: wiki-builder writes.
IMG_EMBED = re.compile(
    r"!\[\[([^\]|\n]+\.(?:png|jpe?g|gif|svg|webp|tiff?|bmp|avif))(?:\|[^\]\n]*)?\]\]", re.I)

def split_frontmatter(text):
    # BOM only -- never whitespace: Obsidian reads properties only when the
    # opening fence is the very first line of the file, so a leading blank
    # line means the "frontmatter" renders as literal text.  The lenient
    # lstrip() here scanned such an entry as clean while a single-file
    # lint_entry run (and Obsidian itself) called it no-frontmatter.
    text = text.lstrip("\ufeff")
    if not text.startswith("---\n"): return None, text, False
    # The CLOSING fence is a line that is exactly `---`.  `find("\n---")`
    # accepted any line merely STARTING with three dashes -- `----`,
    # `--- text` -- swallowing the junk (and, for `----`, leaking the leftover
    # `-` into the body), so an entry whose broken fence Obsidian refuses to
    # parse scanned completely clean while lint_entry (whose parser requires
    # the exact line) reported item 1 on the same file.
    m = re.compile(r"(?m)^---$").search(text, 4)
    if m is None: return None, text, False
    after = text[m.end():]                        # starts at the fence line's own "\n" (or EOF)
    body = after.lstrip("\n")
    blank_after = (len(after) - len(body)) >= 2   # ≥2 leading newlines ⇒ a blank line after the fence
    return text[4:m.start()].strip("\n"), body, blank_after

# Key regex shared by parse_fm, the key_order scan and the item-2 quoting scan, so
# all three see the same keys.  It admits digits and hyphens ("f1-score:"); the old
# ^([A-Za-z_]+): silently dropped such keys, so an off-schema key with a digit in it
# was never reported and never counted as a duplicate.
FM_KEY = re.compile(r"^([A-Za-z_][A-Za-z0-9_-]*)\s*:(.*)$")
FM_ITEM = re.compile(r"^\s*-(?:\s+(.*)|\s*)$")

def unquote(raw):
    """Decode a validated YAML scalar; malformed input raises ValueError."""
    return parse_scalar(raw)[0]

def split_flow(inner):
    """Split a flow-list payload, respecting YAML quote and escape boundaries."""
    out, buf, quote = [], [], None
    i = 0
    while i < len(inner):
        ch = inner[i]
        if quote:
            buf.append(ch)
            if quote == '"' and ch == "\\" and i + 1 < len(inner):
                i += 1
                buf.append(inner[i])
            elif ch == quote:
                if quote == "'" and i + 1 < len(inner) and inner[i + 1] == "'":
                    i += 1
                    buf.append(inner[i])
                else:
                    quote = None
        elif ch in "\"'" and not "".join(buf).strip():
            quote = ch
            buf.append(ch)
        elif ch == ",":
            out.append("".join(buf).strip())
            buf = []
        else:
            buf.append(ch)
        i += 1
    out.append("".join(buf).strip())
    return [x for x in out if x != ""]


def raw_scalar(fm_raw, key):
    """The literal text after `key:` in the frontmatter, or None if absent.

    `parse_fm` deliberately collapses a bare `parents:` and a flow-form
    `parents: []` to the same `[]` — for every consumer that wants the VALUE
    they are the same empty list.  Two item-2 checks want the SPELLING instead:
    a bare key is YAML null, which Obsidian renders as an empty text field
    rather than an empty list under the vault's `multitext` type, and a quoted
    `read: "false"` is a string that renders as a checked box.  Both are
    invisible to the parsed value and visible only here.
    """
    for line in fm_raw.split("\n"):
        m = FM_KEY.match(line)
        if m and m.group(1) == key:
            return strip_comment(m.group(2)).strip()
    return None


def has_block_items(fm_raw, key):
    """True when `key:` is followed by at least one `- item` line."""
    seen = False
    for line in fm_raw.split("\n"):
        m = FM_KEY.match(line)
        if m:
            seen = (m.group(1) == key)
            continue
        if seen and FM_ITEM.match(line):
            return True
    return False


def parse_fm(fm, bad=None):
    """Frontmatter -> {key: str | [str]}.

    Handles the three list spellings wiki-builder writes: block form, flow form
    (`sources: ["stub"]`) and blank.  Flow form used to fall through to the
    scalar branch, so `sources: ["stub"]` parsed as the STRING `["stub"]` — no
    entry written that way was ever recognised as a stub, and a flow-form
    `aliases:` was invisible to alias-collision and backfill alike.

    `bad`, when given, collects every non-blank line that is neither a key nor
    a list item under a list key — an indented/nested key, stray prose, an
    orphan `- item`.  Silently dropping one hid an invalid frontmatter line
    from the whole scan (no item1, no anything) while a single-file lint_entry
    run reported it.
    """
    d, key = {}, None
    for line in fm.split("\n"):
        if not line.strip() or line.lstrip().startswith("#"): continue
        mi = FM_ITEM.match(line)
        if mi and key is not None and isinstance(d.get(key), list):
            val = (mi.group(1) or "").strip()
            try:
                d[key].append(unquote(val))
            except ValueError:
                if bad is not None: bad.append(line)
                d[key].append(None)
            continue
        m = FM_KEY.match(line)
        if not m:
            if bad is not None: bad.append(line)
            continue
        key, raw = m.group(1), strip_comment(m.group(2)).strip()
        if raw == "":
            d[key] = []                                  # blank, or a block list to follow
        elif raw.startswith("[") and raw.endswith("]"):
            values = []
            for item in split_flow(raw[1:-1]):
                try:
                    values.append(unquote(item))
                except ValueError:
                    if bad is not None: bad.append(line)
                    values.append(None)
            d[key] = values
            key = None                                   # a flow list ends on its own line
        else:
            try:
                d[key] = unquote(raw)
            except ValueError:
                if bad is not None: bad.append(line)
                d[key] = None
            key = None
    return d

def source_stem(item):
    """``(stem, ext)`` of one `sources:` item, both case-folded.

    The pair is the identity of the DOCUMENT the item names, so everything that
    can vary without changing which document that is gets dropped: the `[[ ]]`
    wrapper, a `#page=N` anchor, a display pipe, and any folder qualification
    (`Sources/PDFs/X.pdf` and `X.pdf` are one file). Case AND Unicode
    normalization are folded because the documented vault lives on a filesystem
    that is insensitive to both, where `X.md`, `x.md` and the NFD spelling of
    either are all the same name.

    `("", "")` when the item carries no extension at all — the "stub" marker, or
    a malformed item whose missing extension is the form check's finding.
    """
    inner = (item or "").strip()
    if inner.startswith("[[") and inner.endswith("]]"): inner = inner[2:-2]
    inner = inner.split("|",1)[0]                       # display pipe
    inner = inner.split("#",1)[0]                       # #page=N anchor
    inner = inner.replace("\\","/").rsplit("/",1)[-1]   # folder qualification
    stem, dot, ext = inner.rpartition(".")
    if not dot: return "", ""
    # NFC as well as case, for the reason fold_name() gives: a `.pdf` item read
    # off an APFS disk is NFD and the `.md` twin typed into a note is NFC — one
    # document to the filesystem and to Obsidian, two unequal strings here, so
    # the item4 pair went unreported. §7 requires this to agree exactly with
    # wiki-builder's lint_entry.source_stem(); keep the two lines identical.
    return (unicodedata.normalize("NFC", stem.strip()).lower(),
            unicodedata.normalize("NFC", ext.strip()).lower())

WIKILINK = re.compile(r"(?<!\!)\[\[([^\]\|]+)(?:\|([^\]]+))?\]\]")  # (?<!!) excludes ![[embeds]]
ANYLINK  = re.compile(r"!?\[\[[^\]]*\]\]")                          # links + embeds, for masking

#: A Flashcards heading, anchored to a whole line.  A substring `find()`
#: matched the tail of a `### Flashcards` heading (mis-reporting a present
#: separator as missing) and a mid-line mention of the literal text, splitting
#: the entry's prose at a byte inside a sentence.  TOLERANT on purpose, the
#: way Obsidian renders headings (≤3 leading spaces, `##`/`###`, any run of
#: spaces/tabs before the word): every one of those spellings shows the reader
#: a Flashcards section, so treating a non-canonical one as MISSING prescribed
#: adding a second section beside the one Obsidian already renders.  The
#: canonical spelling is `## Flashcards` exactly; a tolerated variant gets its
#: own item19 finding ("fix the heading"), never "add the section".
_FLASH_HEAD_LINE = re.compile(r"^ {0,3}#{2,3}[ \t]+Flashcards[ \t]*$")
_FLASH_HEAD_CANON = re.compile(r"^## Flashcards[ \t]*$")

def regions(body):
    """``(prose, related_line, flashcards_section, flash_off, flash_head)``.

    The Related line and the Flashcards heading are located on the
    FENCED-STRIPPED text (line count preserved, so raw offsets line up): a
    ``**Related:**`` or ``## Flashcards`` shown inside a listing is a sample,
    not a section, and reading it as one truncated the entry's prose there —
    the sample was parsed as the real footer/section (phantom findings whose
    fix edits the listing) while the text past the fence, real findings
    included, vanished from every prose scan.  ``flash_off`` is the heading's
    character offset in the RAW body (−1 when absent); ``flash_head`` is the
    heading line as spelled.
    """
    lines = body.split("\n")
    masked = strip_fenced(body).split("\n")
    rel_i = flash_i = None
    for i, ln in enumerate(masked):
        if rel_i is None and ln.startswith("**Related:**"):
            rel_i = i
        if flash_i is None and _FLASH_HEAD_LINE.match(ln):
            flash_i = i
    offs, pos = [], 0
    for ln in lines:
        offs.append(pos); pos += len(ln) + 1
    rel = lines[rel_i] if rel_i is not None else ""
    cut = len(body)
    if rel_i is not None: cut = offs[rel_i]
    fc = offs[flash_i] if flash_i is not None else -1
    if fc != -1 and fc < cut: cut = fc
    flash_head = lines[flash_i] if flash_i is not None else ""
    return body[:cut], rel, (body[fc:] if fc != -1 else ""), fc, flash_head

# `importance` is a LEGACY key — removed from wiki-builder's schema, never written on a new entry,
# but still present (populated) on every entry generated before the removal. Nothing strips it and
# nothing flags it. It stays in CANON so a legacy entry carrying it in its historical slot is not
# reported as an "unexpected frontmatter key" or as out of schema order; it is deliberately absent
# from the required-key checks and from the never-quoted list below.
CANON = ["title","type","aliases","sources","created","updated","description","tags","importance","parents","read"]

#: The keys that must be PRESENT on every entry, stub included — CANON minus
#: the one optional key (`aliases`) and the retired one (`importance`).  This
#: is wiki-builder's `lint_entry.MANDATORY_KEYS`, in the same order and with
#: the same members; the two lists say the same thing about the same schema and
#: a vault-wide run must not report fewer missing keys than a single-file lint.
#: Only four of the nine used to be checked here, so an entry with no `title:`
#: produced ZERO findings from this whole scan — item 5 and item 16 are both
#: gated on a title, and it also drops out of `surf_map`, `title_forms` and
#: `rename_candidates`, so nothing backfills toward it and every
#: `[[slug|label]]` aimed at it passes the item-18 label test unconditionally.
MANDATORY_KEYS = [k for k in CANON if k not in ("aliases", "importance")]

#: The bare YAML booleans `read:` may carry.  A quoted "false" is a STRING, and
#: Obsidian's checkbox property renders any non-empty string as checked — so a
#: note the user has not read displays as read, silently, which is the one
#: failure this field cannot afford.  CONVENTIONS.md §2d.
READ_BOOLEANS = {"true", "false"}

#: The spellings of YAML null a `read:` key can carry: a bare key, `null` in any
#: case, and `~`.  These are NOT a type error — there is no value in them to
#: retype — so they route with the missing key, not with `read: yes`.  See the
#: `read:` block in `scan()`.
READ_NULLS = {"", "null", "~"}
VALID_TAGS = {"mathematics","statistics","physics","chemistry","biology","earth-science",
 "medicine","engineering","computer-science","psychology","sociology","anthropology",
 "economics","finance","political-science","linguistics","history","philosophy","literature","law",
 "business","entrepreneurship","education","architecture","art","music","machine-learning"}  # the 27-discipline enum
TAG_ALIASES = {"ml":"machine-learning","ai":"machine-learning","artificial-intelligence":"machine-learning",
 "cs":"computer-science","comp-sci":"computer-science","poli-sci":"political-science",
 "econ":"economics","bio":"biology","chem":"chemistry","phys":"physics",
 "stats":"statistics","math":"mathematics","maths":"mathematics","lit":"literature",
 "investing":"finance","trading":"finance",
 "startup":"entrepreneurship","startups":"entrepreneurship"}  # safe auto-expansions

#: Frontmatter keys that are Obsidian's own, not this schema's. They are NOT
#: `item2` "unexpected key" findings: item 2 is a class-1 fix-in-place, and the
#: only determinate reading of "fix an unexpected key in place" is to delete it
#: — which throws away app/publish configuration the USER set, in a field this
#: plugin never writes and cannot reconstruct. They route report-only through
#: `item2/obsidian-key` instead. A genuinely off-schema key (`mood:`, a
#: stacked-merge scar) is still a plain `item2`.
OBSIDIAN_KEYS = {"cssclasses", "cssclass", "publish", "permalink", "cover",
                 "image", "banner", "icon"}


def tag_canonical(tag_slug):
    """The enum slug a raw tag slug denotes: alias expanded, case folded.

    The duplicate-tag check has to run on THIS, not on the raw slug. `#ml` and
    `#machine-learning` are two raw slugs and one discipline: the raw check saw
    no duplicate, while item 8's own mandated fix ('rewrite as
    "#machine-learning"') then produced the duplicate it had just certified
    absent. Same for a case variant — `#Machine-Learning` folds onto
    `#machine-learning`.  Returns the raw slug lowercased when it denotes
    nothing in the enum, so an off-enum tag still groups with itself.
    """
    low = (tag_slug or "").lower()
    if low in VALID_TAGS:
        return low
    return TAG_ALIASES.get(low, low)


WORD = re.compile(r"[A-Za-z0-9]+")

_FENCE_RE = re.compile(r"^\s*(`{3,}|~{3,})(.*)$")


def strip_fenced(text):
    """Blank every line inside a ``` / ~~~ fenced code block, line count kept.

    A fenced block is a LISTING: its contents are shown, not asserted, so a
    scan that reads them as frontmatter or as prose reports the sample rather
    than the entry.  Line count is preserved so any offset computed against the
    original still lines up.

    CommonMark 4.5: a fence closes only on a run of the SAME character at
    least as long as the opener, so a ``` sample shown inside a ```` block is
    content, not a close.  A blind toggle inverted the masking there, and the
    `[[link]]` inside the outer listing came back item10/dangling — whose
    Task-2 remedy edits the listing.
    """
    out, fence = [], None            # fence = the opening run, e.g. "````"
    for ln in (text or "").split("\n"):
        m = _FENCE_RE.match(ln)
        if m and fence is None:
            fence = m.group(1)
            # Retain nested/list fences while rejecting a more-indented sample
            # as the closer of a top-level fence. Tabs count as four columns.
            fence_indent = max(3, len(ln[:m.start(1)].expandtabs(4)))
            out.append("")
            continue
        if (m and m.group(1)[0] == fence[0]
                and len(m.group(1)) >= len(fence) and not m.group(2).strip()
                and len(ln[:m.start(1)].expandtabs(4)) <= fence_indent):
            fence = None
            out.append("")
            continue
        out.append("" if fence is not None else ln)
    return "\n".join(out)


#: An inline code span: a run of N backticks, content, and a closing run of the
#: SAME length.  Not `` `[^`]*` ``, which reads ``` ``[[x]]`` ``` as two empty
#: spans around a bare `[[x]]` and leaves the link visible to whatever is
#: reading — an item-10 dangler whose remedy creates a file for a sample of
#: link syntax.  Line-bounded on purpose: a code span may legally span a line
#: break, but honouring that lets one stray backtick swallow the rest of an
#: entry and HIDE real links, which is the costlier direction to be wrong in.
_INLINE_CODE = re.compile(r"(`+)[^\n]*?\1(?!`)")

#: An indented code block's line: four spaces, or a tab (CommonMark 4.4).
_INDENT_CODE = re.compile(r"^(?: {4}|\t)")
#: A list-item opener, at CommonMark's ≤3 spaces of leading indent.  A list
#: item's continuation content is indented for exactly the reason code is,
#: which is the one case that must NOT be read as code.
_LIST_ITEM = re.compile(r"^ {0,3}(?:[-*+]|\d{1,9}[.)])(?:\s|$)")


def strip_indented(text):
    """Blank every line of an INDENTED (4-space / tab) code block.

    The third listing spelling, after ``` and ~~~.  Obsidian renders it as
    code like the other two, so a `[[target]]` inside one links nothing and
    reporting it as dangling prescribes creating a file for something only
    ever shown.

    CommonMark's rule, applied conservatively.  An indented code block may
    only start where a new block can start — after a blank line — so it never
    interrupts a paragraph.  The look-alike that is *not* code is a **list
    item's continuation content**, indented for exactly that reason, so a run
    whose nearest preceding non-blank line is a list item, or is itself
    indented (i.e. already inside one), is left alone.  Erring that way is
    deliberate and one-directional: masking a list continuation would HIDE a
    real dangling link, while declining to mask one only leaves the behaviour
    that was there before.  Line count is preserved, as `strip_fenced` does.
    """
    lines = (text or "").split("\n")
    out = list(lines)
    prev_nonblank = None
    i, n = 0, len(lines)
    while i < n:
        ln = lines[i]
        if not ln.strip():
            i += 1
            continue
        starts_block = (i == 0) or (not lines[i - 1].strip())
        in_list = prev_nonblank is not None and (
            _LIST_ITEM.match(prev_nonblank) or prev_nonblank[:1].isspace())
        if _INDENT_CODE.match(ln) and starts_block and not in_list:
            # Consume the block: indented lines, and the blank lines between
            # them, up to the last indented line.
            j, last = i, i
            while j < n:
                if not lines[j].strip():
                    j += 1
                    continue
                if not _INDENT_CODE.match(lines[j]):
                    break
                last = j
                j += 1
            for k in range(i, last + 1):
                out[k] = ""
            prev_nonblank = lines[last]
            i = last + 1
            continue
        prev_nonblank = ln
        i += 1
    return "\n".join(out)


def strip_code(text):
    """Every LISTING blanked: fenced, indented, and inline code spans.

    What is left is what this entry ASSERTS, with everything it merely SHOWS
    removed.  A scan that has to distinguish the two — item 10 is the one that
    matters, because its remediation CREATES the file it names — must read
    this and not the raw prose: a `[[target-note]]` printed in a listing or
    quoted in a code span is a sample of link syntax, not a link, and Obsidian
    renders it as literal text.  `build_backfill` already reads the
    fenced-stripped form, and for the same reason.

    All three markdown spellings of a listing are covered, because a check
    that knows only one of them is not a rule about listings — it is a rule
    about backticks, and the entry that used the other spelling gets the
    destructive finding.
    """
    return _INLINE_CODE.sub(lambda m: " " * len(m.group(0)),
                            strip_indented(strip_fenced(text)))


def plural_surface(title):
    """The plural SURFACE form of a title: only the HEAD (last) token inflects.

    `pluralize` is a one-TOKEN function (shared/scripts/plurals.py); handing it
    a whole title fails every irregular in its table, because a phrase is never
    a key in it — "Confusion matrix" came back "Confusion matrixes" (the final
    `x` read as a sibilant) and "Hypothesis" as "Hypothesises".  So the real
    plural of an irregular-headed title never entered the surface map, and no
    entry could ever be backfilled from a text that spells it correctly.
    Capitalisation is irrelevant here — the surface map is keyed lowercased —
    but the table lookups are lowercase-only, so the head is folded for them.
    """
    m = re.search(r"([A-Za-z]+)([^A-Za-z]*)$", title or "")
    if not m:
        return title
    head = m.group(1)
    plural = pluralize(head.lower())
    if head[:1].isupper():                       # keep the title's own casing
        plural = plural[:1].upper() + plural[1:]
    return title[:m.start(1)] + plural + m.group(2)

def _index_surfaces(surf_map):
    """Group surface forms by their token sequence: "roc curve" -> [surface, ...].

    Each entry keeps the surface's leading offset (the count of non-alphanumeric
    characters before its first token) so the literal text can still be verified
    against the document -- a surface is only a hit when it appears VERBATIM,
    exactly as the old alternation required.
    """
    by_tokens, maxwords = {}, 0
    for s in surf_map:
        # Plurals and aliases cannot make a forbidden bare destination safe:
        # excluding only "entropy" still proposed [[entropy|entropies]].
        if s in COMMON_NOUNS or fold_name(surf_map[s]) in COMMON_NOUNS: continue
        m = list(WORD.finditer(s))
        if not m: continue
        key = " ".join(t.group(0) for t in m)
        by_tokens.setdefault(key, []).append((s, m[0].start()))
        maxwords = max(maxwords, len(m))
    for cands in by_tokens.values():       # longest surface first, as the alternation was
        cands.sort(key=lambda sc: -len(sc[0]))
    return by_tokens, maxwords


def _boundary_ok(low, start, end):
    """Both edges must sit on a non-[A-Za-z0-9] boundary (the old lookarounds)."""
    if start > 0 and low[start-1].isascii() and low[start-1].isalnum(): return False
    if end < len(low) and low[end].isascii() and low[end].isalnum(): return False
    return True


def _scan_surfaces(text, by_tokens, maxwords):
    """Yield ``(surface, matched_text)`` for every verbatim surface hit in `text`.

    Replaces a single regex alternation over EVERY surface form, which was
    re-run against every entry: that is O(entries x surfaces), measured at 84s
    for 2000 entries and extrapolating to ~40 min at 10000.  This tokenizes the
    text once and looks n-grams up in a dict, i.e. O(total tokens) with the
    surface count entering only through `maxwords`.

    Semantics are identical to the alternation it replaces, which is why the
    matches are collected and then resolved rather than taken greedily: an
    alternation sorted longest-first picks the LEFTMOST match, breaks ties by
    length, and never overlaps a previous match.  Anchoring on tokens alone got
    that wrong when one surface starts with punctuation and another starts one
    character later ("(cross)" vs "cross) foo").
    """
    toks = [(m.group(0).lower(), m.start(), m.end()) for m in WORD.finditer(text)]
    low = text.lower()
    n = len(toks)
    hits = []
    for i in range(n):
        for k in range(1, min(maxwords, n - i) + 1):
            cands = by_tokens.get(" ".join(t[0] for t in toks[i:i + k]))
            if not cands: continue
            for surface, lead in cands:
                start = toks[i][1] - lead
                end = start + len(surface)
                if start < 0 or low[start:end] != surface: continue
                if not _boundary_ok(low, start, end): continue
                hits.append((start, -len(surface), surface, end))
    last_end = 0
    for start, _neg, surface, end in sorted(hits):   # leftmost, then longest
        if start < last_end: continue                # non-overlapping, as re.finditer is
        last_end = end
        yield surface, text[start:end]


def build_backfill(entries, surf_map):
    """Task 2 worklist: bare-text mentions of another entry's surface forms."""
    by_tokens, maxwords = _index_surfaces(surf_map)
    backfill = []
    if not by_tokens:
        return backfill
    files = {fold_name(sl): sl for sl in entries}
    alias_owners = {}
    for sl, e in entries.items():
        for alias in e.get("aliases", []):
            alias_owners.setdefault(fold_name(alias), set()).add(sl)
    for sl, e in entries.items():
        if e["is_stub"]: continue  # Task 2 backfill operates on full entries only
        prose = strip_code(e["prose"])
        linked = set()
        for link in WIKILINK.finditer(prose):
            target = link.group(1).split("#", 1)[0].split("^", 1)[0].strip()
            target = target.replace("\\", "/").rsplit("/", 1)[-1]
            if target.lower().endswith(".md"):
                target = target[:-3]
            key = fold_name(target)
            owner = files.get(key)
            if owner is None and len(alias_owners.get(key, ())) == 1:
                owner = next(iter(alias_owners[key]))
            if owner is not None:
                linked.add(owner)
        masked = ANYLINK.sub(lambda m: " "*len(m.group(0)), prose)
        # Blank every line a link may not be written on, for the same reason in
        # each case: the backfill worklist proposes linking the FIRST occurrence,
        # so a first occurrence sitting somewhere unlinkable is an un-actionable
        # item that also HIDES the linkable occurrence further down.
        #   * whole-line italic captions — item 12 forbids wikilinks in captions;
        #   * markdown TABLE ROWS — item 10 forbids wikilinks in table cells;
        #   * fenced code blocks — a listing is shown, not asserted, and a link
        #     written inside one renders as literal `[[...]]` text.
        masked = "\n".join(
            ("" if (re.match(r"^\s*\*(?!\*).*\*\s*$", ln) or re.match(r"^\s*\|", ln))
             else ln)
            for ln in masked.split("\n"))
        proposed = set()
        for surface, matched in _scan_surfaces(masked, by_tokens, maxwords):
            tgt = surf_map.get(surface)
            if not tgt or tgt == sl or tgt in proposed: continue
            if tgt in linked: continue
            proposed.add(tgt)
            backfill.append((sl, tgt, matched, surface))
    return backfill


def iter_entry_files(wiki, on_error=None):
    """Every `.md` under `wiki`, RECURSIVELY and sorted (dot-dirs skipped).

    `os.listdir` was flat, so an entry filed in `Wiki/sub/` was invisible to the
    whole scan — and every wikilink pointing at it was reported as dangling.
    wiki-builder's vault_index.py has always walked recursively; this matches it.
    """
    out = []
    seen_dirs = set()
    for dirpath, dirnames, filenames in os.walk(wiki, followlinks=True, onerror=on_error):
        # followlinks, because a synced or shared subfolder under Wiki/ is a
        # symlink in plenty of real vaults, and skipping it made every link
        # into it read as dangling -- whose documented fix writes a stub over
        # the entry. `seen_dirs` keeps a symlink loop from walking forever.
        try:
            key = os.stat(dirpath).st_ino, os.stat(dirpath).st_dev
        except OSError:
            key = dirpath
        if key in seen_dirs:
            dirnames[:] = []
            continue
        seen_dirs.add(key)
        dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))
        for name in filenames:
            if name.lower().endswith(".md") and not name.startswith("."):
                out.append(os.path.join(dirpath, name))
    return sorted(out)


#: Extensions a wikilink may legitimately name that are not wiki entries: the
#: document forms CONVENTIONS 6/7 blesses in a `sources:` list. A link to one
#: is not dangling and must never be stubbed.
_DOC_EXTS = {".pdf", ".epub", ".docx", ".md", ".html", ".txt"}


def image_index(images):
    """Every filename in the image folder, folded — or None when not given.

    Folded, not `os.path.isfile`, for the reason `fold_name` gives: the
    documented vault sits on a case- and normalization-insensitive volume, so
    an entry embedding `![[Doe_X_2025_Fig_2.png]]` against a file written
    `doe_x_2025_fig_2.png` displays the image. An `isfile` probe on the
    case-SENSITIVE Linux filesystem the plugin is tested on says it is missing,
    and the finding tells the user to fix an embed that already works.

    Walked recursively although CONVENTIONS §1 makes `Sources/Images/` flat:
    Obsidian resolves an embed by basename wherever the file sits, so a user
    who has nested a subfolder gets no false "missing" findings out of it.
    """
    if images is None:
        return None
    names = set()
    for _dirpath, _dirnames, _filenames in os.walk(images):
        for _n in _filenames:
            if not _n.startswith("."):
                names.add(fold_name(_n))
    return names


def scan(wiki, images=None):
    """Parse every entry in the `wiki` folder; return the Step 0 model as a dict.

    `images` is the vault's `Sources/Images/` folder, or None. CONVENTIONS §1
    names this skill the validator of the embeds pointing there, and until
    `--images` existed nothing in the skill had a path to that folder at all:
    an entry embedding a figure that is not on disk produced an empty problem
    list here while paper-summarizer's `note_lint.py --images` reported the
    same embed on an `Articles/` note. It is also the detector CONVENTIONS §1a
    relies on for `Wiki/` — a source rename renames every figure with it, and
    the embeds left pointing at the old stem are silent otherwise.
    """
    img_fold = image_index(images)
    entries, problems = {}, []
    # Every slug whose FILE is on disk, whether or not it parsed as an entry.
    # A link to an unparseable file resolves in Obsidian, so it is not dangling
    # -- and stubbing it would write over the file.
    on_disk = set()
    seen_paths = {}
    ambiguous_files = set()
    def walk_error(exc):
        location = os.path.relpath(exc.filename, wiki) if exc.filename else "."
        problems.append((location, "item0", "unreadable wiki directory: %s" % exc))

    for path in iter_entry_files(wiki, on_error=walk_error):
        fn = os.path.basename(path)
        sl = fn[:-3]
        rel = os.path.relpath(path, wiki)
        # Obsidian resolves a wikilink by basename, case-insensitively, so two
        # files with the same stem in different folders — INCLUDING two stems
        # that differ only in case or Unicode normalization, which are one name
        # to Obsidian and to the vault's own APFS volume — are one slug with
        # two bodies. Report, keep the first.
        if fold_name(sl) in seen_paths:
            ambiguous_files.add(fold_name(sl))
            prev_sl, prev_rel = seen_paths[fold_name(sl)]
            problems.append((sl,"item5",f'slug "{sl}" occurs in two files ({prev_rel} and {rel}'
                                        f'{"" if prev_sl == sl else ", stems differing only in case/normalization"}) — '
                                        f'Obsidian resolves [[{sl}]] to only one of them; rename or merge'))
            continue
        seen_paths[fold_name(sl)] = (sl, rel)
        # One unreadable file must not take the scan down with it: an unguarded
        # read() on a binary .md / dangling symlink / unreadable file raised, and
        # the traceback left stdout EMPTY, so the caller got no scan at all.
        try:
            # utf-8-SIG strips a BOM, which would otherwise sit in front of
            # the opening `---` and report a valid entry as having no
            # frontmatter.  Universal newlines are load-bearing too and are why
            # nothing here re-spells CRLF: text mode translates \r\n to \n on
            # read, so every line-oriented check below sees one line ending.
            # Reading with `newline=""` would leave a \r on every parsed value
            # AND blind the blank-line-after-frontmatter probe, which counts
            # leading "\n" and would see "\r\n\r\n".
            with open(path, encoding="utf-8-sig") as fh:
                text = fh.read()
        except (OSError, UnicodeDecodeError) as exc:
            problems.append((sl,"item0",f"unreadable: {type(exc).__name__}: {exc}"))
            on_disk.add(sl)
            continue
        fm_raw, body, blank_after = split_frontmatter(text)
        if fm_raw is None:
            problems.append((sl,"item1","no YAML frontmatter"))
            on_disk.add(sl)
            continue
        _fm_bad = []
        fm = parse_fm(fm_raw, _fm_bad)
        for _ln in _fm_bad:
            problems.append((sl,"item1",
                             f"unparseable frontmatter line: {_ln.strip()[:60]!r}"))
        def _scalar(k):                    # a key written as a list is not a scalar
            v = fm.get(k, "")
            return v if isinstance(v, str) else ""
        sources = fm.get("sources") or []
        if isinstance(sources, str): sources = [sources]
        is_stub = (sources == ["stub"])
        title = _scalar("title")
        aliases = ([a for a in fm["aliases"] if isinstance(a, str) and a]
                   if isinstance(fm.get("aliases"), list) else [])
        tags_raw = fm.get("tags", []) if isinstance(fm.get("tags"), list) else ([fm["tags"]] if fm.get("tags") else [])
        tags_raw = [t.strip() for t in tags_raw if isinstance(t, str) and t.strip()]  # decoded, non-null tags
        tag_slugs = [t.lstrip("#").strip() for t in tags_raw]          # discipline slugs without the # prefix, for MOC/hierarchy use
        desc = _scalar("description")
        created = _scalar("created"); updated = _scalar("updated")
        key_order = [m.group(1) for line in fm_raw.split("\n") if (m:=FM_KEY.match(line))]
        prose, rel, fcsec, flash_off, flash_head = regions(body)
        entries[sl] = dict(slug=sl, title=title, aliases=aliases, type=_scalar("type"),
                           tags_raw=tags_raw, tag_slugs=tag_slugs, is_stub=is_stub,
                           sources=sources, sources_is_list=isinstance(fm.get("sources"), list),
                           body=body, prose=prose, rel=rel, fcsec=fcsec, desc=desc,
                           created=created, updated=updated, blank_after=blank_after,
                           parents=fm.get("parents", []) if isinstance(fm.get("parents"), list) else [],
                           key_order=key_order, fm_raw=fm_raw,
                           flash_off=flash_off, flash_head=flash_head,
                           has_flashcards=(flash_off != -1),
                           has_related=bool(rel))

    # fold_name(slug) -> on-disk slug, for every comparison that asks "is this
    # the same FILE?" — Obsidian and the vault's APFS volume both resolve
    # case- and normalization-insensitively, so [[ROC-curve]] against
    # roc-curve.md is a resolving link with a cosmetic defect, not a dangler.
    fold_of = {}
    for _sl in entries:
        fold_of.setdefault(fold_name(_sl), _sl)
    # Files on disk that did NOT parse into `entries`: a link to one of these
    # resolves in Obsidian, so it is not a dangler and must never be stubbed.
    on_disk_fold = {fold_name(_sl) for _sl in on_disk} - set(fold_of)
    # fold_name(alias) -> (owning slug, the alias as spelled). Obsidian
    # resolves [[tpr]] to the entry whose `aliases:` carries "tpr" when no FILE
    # answers to that name -- references/writing.md calls an alias an
    # alternative slug, and wiki-builder's find_collisions.build_targets probes
    # aliases for exactly that reason. A file always wins over an alias, so
    # this is consulted only after the slug and on-disk lookups, and it is not
    # a fallback for them. Keep ambiguous owners separate: item 18 reports
    # the collision, but item 10 must not choose a rewrite target for it.
    alias_of = {}
    ambiguous_aliases = set()
    for _sl, _e in sorted(entries.items()):
        for _a in _e["aliases"]:
            _k = fold_name(_a)
            if _k:
                if _k in alias_of and alias_of[_k][0] != _sl:
                    ambiguous_aliases.add(_k)
                alias_of.setdefault(_k, (_sl, _a))

    for sl,e in entries.items():
        fm_raw, is_stub, title = e["fm_raw"], e["is_stub"], e["title"]
        # ---- item 5: slug == filename; bare-slug common noun ----
        _newslug = slug(title) if title else ""
        if title and not _newslug:
            problems.append((sl,"item5",f'title "{title[:60]}" cannot be slugged automatically (it reduces to '
                                        f'the empty slug, or its slug exceeds the filename budget) — ask the '
                                        f'user for an ASCII-representable, shorter title; DO NOT rename the file'))
        elif title and _newslug != sl:
            problems.append((sl,"item5",f'title "{title}" slugs to "{_newslug}" ≠ filename'))
        if "-" not in sl and sl in COMMON_NOUNS:
            problems.append((sl,"item5",f'bare-slug common noun "{sl}" — qualify the title'))
        # ---- item 2: field order, required keys, duplicate keys, quoting ----
        known = [k for k in e["key_order"] if k in CANON]
        if [CANON.index(k) for k in known] != sorted(CANON.index(k) for k in known):
            problems.append((sl,"item2","fields out of schema order: "+", ".join(e["key_order"])))
        for k in e["key_order"]:
            if k in CANON or k == "roots":        # roots gets a dedicated migration message below
                continue
            if k.lower() in OBSIDIAN_KEYS:
                # REPORT ONLY. See OBSIDIAN_KEYS: this is Obsidian's own
                # property, not a schema violation, and the only determinate
                # reading of an item-2 "fix in place" is deletion — which
                # silently destroys appearance/publish configuration the user
                # set and this plugin can never reconstruct.
                problems.append((sl,"item2/obsidian-key",
                                 f'frontmatter key "{k}" is an Obsidian built-in property, not part of '
                                 f'the entry schema — REPORT ONLY, DO NOT DELETE OR REORDER. It is the '
                                 f"user's own appearance/publish configuration; deleting it is the only "
                                 f'thing "fix in place" could mean here, and nothing can restore it. '
                                 f'Mention it for the user to keep or remove'))
                continue
            problems.append((sl,"item2",f'unexpected frontmatter key "{k}"'))
        if len(e["key_order"]) != len(set(e["key_order"])):
            problems.append((sl,"item2","duplicate frontmatter key (stacked-body artifact?)"))
        # Every MANDATORY key must be PRESENT, whatever its value — a missing
        # KEY and a missing VALUE are two findings and both are real (item 7
        # reports an absent description, item 3 an absent date; item 2 reports
        # that the key itself is gone). This used to name four keys by hand,
        # and the five it omitted included `title:`, whose absence silently
        # switched off item 5, item 16, the rename candidate and the entry's
        # whole contribution to the surface and display-label maps — so the
        # entry came back from a whole-vault QC pass with nothing at all
        # against it, while a single-file lint_entry run on it reported two.
        # `tags` and `read` keep their own messages below (a missing `tags:`
        # may be a roots→tags migration, and a missing `read:` is report-only).
        for _k in MANDATORY_KEYS:
            if _k in e["key_order"] or _k in ("tags", "read", "title"):
                continue
            problems.append((sl,"item2",f"missing {_k}: key"))
        # A `title:` KEY with no scalar value (bare, null, or a list) is the
        # same silent no-op as a missing key: `title` is "" either way, and
        # everything below gates on the value, not the key — so only the
        # key-absence half of this used to be checked, and a valueless
        # `title:` came back from a whole-vault pass with no findings while a
        # single-file lint reported two.
        if "title" not in e["key_order"] or not title:
            problems.append((sl,"item2",
                             ("missing title: key" if "title" not in e["key_order"]
                              else "title: key carries no value")
                             + " — the entry has no canonical name, so every "
                             "check that starts from one is a silent no-op on it: the item-5 "
                             "slug↔filename comparison, the item-16 opener check, its rename "
                             "candidate, its surface forms for backfill, and the item-18 "
                             "display-label test on every link pointing at it. Ask the user for "
                             "the title; DO NOT invent one from the filename"))
        # read: — the user's review checkbox (CONVENTIONS.md §2d).  Four
        # distinct states, and they route three different ways, which is why
        # they are three messages rather than one:
        #   absent      -> REPORT ONLY.  The linter never writes this field, and
        #                  the only value it could supply is `false`, which would
        #                  mark an entry the user has already read as unread —
        #                  destroying the one piece of state the field exists to
        #                  hold.  Same class as item3/user-action.
        #   present, no -> REPORT ONLY, same class and for the same reason: a
        #   value         bare `read:`, `read: null` and `read: ~` are all YAML
        #                 null, so there is no value here to retype and no sense
        #                 to preserve.  Writing `false` would INVENT one and
        #                 clear a tick the user set — which is precisely the harm
        #                 read-missing is report-only to prevent, so the two
        #                 cannot route differently.  (Contrast item2/parents-null,
        #                 which IS fixed in place: `[]` re-spells an empty value
        #                 that is already empty, and changes nothing.)
        #   wrong type  -> ordinary fix in place.  The meaning is unambiguous;
        #                  only the spelling is wrong, and the value is preserved.
        #   out of order-> already caught by the schema-order check above.
        _read_raw = raw_scalar(fm_raw, "read") or ""
        try:
            _read_value, _read_style = parse_scalar(_read_raw)
        except ValueError:
            _read_value, _read_style = None, "invalid"
        if "read" not in e["key_order"]:
            problems.append((sl,"item2/read-missing",
                             "missing read: key — the user's review checkbox. Report it; "
                             "never write a value, since `false` would mark an entry they "
                             "have already read as unread"))
        elif _read_raw.strip().lower() in READ_NULLS and not has_block_items(fm_raw, "read"):
            problems.append((sl,"item2/read-null",
                             'read: is present but carries no value (%s) — YAML null, not a '
                             'boolean, so Obsidian shows the checkbox unticked while the entry '
                             'records no answer at all. Report it; DO NOT FIX. There is no '
                             'value here to preserve, so writing `false` would invent one and '
                             'clear a tick the user may have set — the same harm, and the same '
                             'report-only class, as a missing read: key'
                             % ("bare `read:`" if not _read_raw.strip()
                                else "`read: %s`" % _read_raw.strip())))
        elif not isinstance(_read_value, str) or _read_value.lower() not in {"true", "false", "yes", "no", "0", "1"}:
            problems.append((sl,"item2/read-unknown",
                             'read: has no recognizable boolean answer (%r) -- REPORT ONLY, '
                             'DO NOT FIX. Neither true nor false can be inferred safely; '
                             'ask the user to supply their review state' % _read_raw))
        elif _read_style != "bare" or _read_value.lower() not in READ_BOOLEANS:
            problems.append((sl,"item2/read-type",
                             'read: must be a bare boolean (`true` / `false`), not %r — a '
                             'quoted "false" is a string, and Obsidian renders any non-empty '
                             'string in a checkbox property as permanently checked; `yes`/`no` '
                             'and `0`/`1` are the same field written in the wrong spelling. '
                             'Fix the spelling, keep the value' % _read_raw))
        # parents: — a bare key is YAML null, not an empty list.  The vault pins
        # the property as `multitext` (.obsidian/types.json), so null renders as
        # an empty TEXT field: the declared type and the value on disk disagree.
        # `[]` is the only spelling that is both a valid empty list and visibly
        # one.  An ordinary fix in place — nothing about the entry changes but
        # the spelling of an empty value.  CONVENTIONS.md §2a.
        if "parents" in e["key_order"] \
                and raw_scalar(fm_raw, "parents") == "" \
                and not has_block_items(fm_raw, "parents"):
            problems.append((sl,"item2/parents-null",
                             "empty parents: is written `parents: []` — a bare key is YAML "
                             "null, which renders as an empty text field rather than an "
                             "empty list under the vault's multitext type"))
        # No missing-importance: check — the field left the schema (see CANON above).
        if "roots" in e["key_order"]:         # the schema replaced roots: with tags: — one targeted message
            if "tags" in e["key_order"]:
                problems.append((sl,"item2",'stale roots: key — the schema replaced roots: with tags:; remove roots: (tags: is already present)'))
            else:
                problems.append((sl,"item2",'old roots: key, no tags: key — migrate roots → tags (one or more #-prefixed discipline slugs from the 27-enum, not a wikilink)'))
        elif "tags" not in e["key_order"]:
            problems.append((sl,"item2","missing tags: key (mandatory — present even when blank on a full entry)"))
        cur = None
        for line in fm_raw.split("\n"):
            mt = FM_KEY.match(line)
            if mt:
                k, val = mt.group(1), strip_comment(mt.group(2)).strip(); cur = None
                try:
                    _value, _style = parse_scalar(val)
                except ValueError:
                    _value, _style = None, "invalid"
                if k in ("title","description") and val and _style != "double":
                    problems.append((sl,"item2",f'{k} must be double-quoted'))
                if k in ("type","created","updated") and (val.startswith('"') or val.startswith("'")):
                    problems.append((sl,"item2",f'{k} must not be quoted'))
                if k in ("aliases","sources","tags","parents"):
                    if val.startswith("[") and val.endswith("]"):    # flow list, complete on this line
                        for iv in split_flow(val[1:-1]):
                            try:
                                _iv_style = parse_scalar(iv)[1]
                            except ValueError:
                                _iv_style = "invalid"
                            if _iv_style != "double":
                                problems.append((sl,"item2",f'{k} item not double-quoted: {iv[:30]}'))
                    else:
                        cur = k
            else:
                mi = re.match(r"^\s*-\s*(.*)$", line)
                if mi and cur:
                    iv = mi.group(1).strip()
                    try:
                        _iv_style = parse_scalar(iv)[1]
                    except ValueError:
                        _iv_style = "invalid"
                    if iv and _iv_style != "double":
                        problems.append((sl,"item2",f'{cur} item not double-quoted: {iv[:30]}'))
        # ---- item 3: dates ----
        for f in ("created","updated"):
            v = e[f]
            if isinstance(v,str) and v:
                if not re.match(r"^\d{4}-\d{2}-\d{2}$", v):
                    problems.append((sl,"item3",f'{f} "{v}" not YYYY-MM-DD'))
                else:
                    try: datetime.datetime.strptime(v, "%Y-%m-%d")
                    except ValueError: problems.append((sl,"item3",f'{f} "{v}" is not a valid date'))
            else:
                problems.append((sl,"item3",f'{f} missing'))
        def _valid(d):
            """The `date` this field denotes, or None when it denotes none.

            **The format finding and the ordering finding are separate, and
            this is the ordering one.** Item 3's `^\\d{4}-\\d{2}-\\d{2}$` check
            one block above already reports an unpadded `2026-1-1` on its own
            line; this parse is deliberately as permissive as `strptime` is,
            because `2026-2-05` names one day and nothing else. Refusing to
            ORDER a date that is merely spelled badly throws away a real
            finding to avoid a formatting question that is already reported —
            and the user is fixing both lines anyway.

            What must not happen is comparing the raw STRINGS, which is the
            bug this replaced: lexically "2026-1-1" sorts after "2026-01-02"
            (a correctly ordered entry routed to the report-only "user must fix
            by hand" bucket) and "2026-12-01" sorts before "2026-2-05" (a
            genuinely reversed pair reported by nobody). Parse first, then
            compare the `date` objects; every unpadded spelling then orders
            exactly as the day it names.
            """
            if not isinstance(d, str) or not d:
                return None
            try:
                return datetime.datetime.strptime(d, "%Y-%m-%d").date()
            except (ValueError, TypeError):
                return None
        # created > updated is REPORT-ONLY, not a fixable violation: wiki-linter never writes created:/updated:
        # (see Dates), so filing it as a lint problem would re-report the same entries forever with nothing the
        # linter can do. Its own item key routes it to the run report's user-action bucket instead.
        # Compared as DATES, never as strings — the strings are only interchangeable
        # with the dates once both are known to be zero-padded, which is what _valid checks.
        _created_d, _updated_d = _valid(e["created"]), _valid(e["updated"])
        if _created_d is not None and _updated_d is not None and _created_d > _updated_d:
            problems.append((sl,"item3/user-action",f'created {e["created"]} > updated {e["updated"]} — impossible ordering (updated is the last merge date, so it cannot precede creation); DO NOT FIX, report for the user to correct by hand'))
        # ---- item 4: sources format ----
        if not e["sources"]:
            problems.append((sl,"item4","sources: is empty; every full entry needs a local source"))
        elif not e["sources_is_list"]:
            problems.append((sl,"item4","sources: must be a list, not a scalar"))
        for i,src in enumerate(e["sources"]):
            if src is None:
                problems.append((sl,"item4","sources: contains a null or invalid item"))
                continue
            if src == "stub":
                if e["sources"] != ["stub"]:
                    problems.append((sl,"item4",'"stub" marker must be the sole source item'))
                continue
            if re.fullmatch(r"\[\[[^\[\]\r\n|#]+\.(?i:pdf)#page=[1-9][0-9]*\]\]", src):
                continue
            if re.fullmatch(r"\[\[[^\[\]\r\n|#]+\.(?i:md)\]\]", src):
                continue
            problems.append((sl,"item4",f'source must be [[Name.pdf#page=N]] with a positive '
                             f'physical page number, or [[Name.md]] without an anchor; '
                             f'URLs, display labels and incomplete wikilinks are invalid: {src}'))
        # No two sources: items may name the same DOCUMENT. paper-summarizer writes a note into
        # Articles/ for every PDF it summarises, so one document sits in the vault under two
        # names — Sources/PDFs/X.pdf and Articles/X.md — and both are legal sources:
        # values. A same-stem clipping may instead be an independent source, so the match
        # needs the markdown note's provenance before any source may be removed.
        # Only a stem collision ACROSS the two extensions counts — an entry may
        # legitimately cite several distinct PDFs and several distinct clippings — and stems compare case- and NFC-insensitively (the documented
        # vault lives on a filesystem that is insensitive to both; see fold_name).
        pdf_by_stem, md_items = {}, []
        for src in e["sources"]:
            if src == "stub": continue
            stem, ext = source_stem(src)
            if not stem: continue
            if ext == "pdf": pdf_by_stem.setdefault(stem, src)   # keep the first spelling
            elif ext == "md": md_items.append((stem, src))
        for stem, md_src in md_items:
            if stem not in pdf_by_stem: continue
            problems.append((sl,"item4/source-identity",
                             f'{md_src} and {pdf_by_stem[stem]} share a filename stem; review the '
                             f'markdown note\'s decoded sources: (or legacy source:) to establish '
                             f'whether it summarizes that PDF. A URL-origin clipping can be '
                             f'independent. Preserve both sources until their identity is confirmed'))
        # ---- item 6: type / API surface (non-Software entries) ----
        if e["type"] != "Software":
            if re.match(r"^[A-Za-z_][\w]*(\.[A-Za-z_][\w]*)+$", title) or "()" in title:
                problems.append((sl,"item6",f'title looks like a code identifier: "{title}"'))
            libalt = "|".join(re.escape(l) for l in LIBS)
            api_fails = [
                (rf"\bIn ({libalt})\b", "In-<library> framing"),
                (rf"\b({libalt})\s+(provides|offers|exposes|has)\b", "<library> provides/offers framing"),
                (r"\bbuilt with `", "'built with `…`' how-to signpost"),
                (r"\bconstructed (with|via) `", "'constructed with/via `…`' how-to signpost"),
                (r"\bcreated (with|by) `", "'created with/by `…`' how-to signpost"),
                (r"\bavailable (through|via|in) `", "'available through `…`' how-to signpost"),
                (r"\buse `[^`]+` to\b", "'use `…` to' how-to signpost"),
                (r"`[^`]+` or `[^`]+`", "`…` or `…` alternative signposts"),
                (r"\bflag enables\b", "kwarg/flag documentation"),
                (r"`[A-Za-z_][A-Za-z0-9_]*\s*=", "backticked kwarg/default-value (`name=`)"),
                (r"`(True|False|None)`", "Python language literal in code form"),
            ]
            for pat,label in api_fails:
                if re.search(pat, e["prose"]):
                    problems.append((sl,"item6",f'API-surface failure string — {label}')); break
            # fenced code block — code listings don't belong in a non-Software entry.
            # Both fence spellings: markdown opens a block with ``` or ~~~, and
            # `strip_fenced` above has always known that, so a `~~~` listing sat
            # in a Concept entry unreported by the one check that exists to find it.
            if re.search(r"(?m)^\s*(?:`{3}|~{3,})", e["body"]):
                problems.append((sl,"item6","fenced code block — code listings belong in a Software entry (strip it, or reclassify if the entry is really software)"))
            # API-identifier cap — ZERO backticked identifiers in a non-Software entry.
            # (Rule change 2026-08-16: the one-name-only-signpost allowance is retired;
            # identifiers live only in the library's own Software entry. A bare file
            # extension and a bracket special token are still not identifiers.)
            inline = re.findall(r"`([^`\n]+)`", re.sub(r"`{3}.*?`{3}", " ", e["prose"], flags=re.S))
            idtoks = [t.strip() for t in inline if t.strip()
                      and not re.fullmatch(r"\.[A-Za-z0-9]+", t.strip())   # not a bare file extension (.csv)
                      and not re.fullmatch(r"\[.+\]", t.strip())]          # not a bracket special token ([CLS])
            if len(idtoks) >= 1:
                problems.append((sl,"item6",f'{len(idtoks)} backticked identifier(s) (cap is 0 in a non-Software entry — API surface lives in the library\'s Software entry): {", ".join(idtoks[:6])}'))
        # ---- item 7: description length + presence (FULL ENTRIES AND STUBS) ----
        # Item 7 is NOT on the stub exemption list: wiki-builder's stub format carries a real
        # description ("Description follows the description field definition"), so the ≤110 cap, the
        # entity-as-subject form and the plain-text rule all apply to a stub exactly as to a full entry.
        # This block used to sit behind `if not is_stub:`, which silently exempted every stub.
        if not e["desc"]: problems.append((sl,"item7","missing description"))
        elif len(e["desc"]) > 110: problems.append((sl,"item7",f'description {len(e["desc"])} chars > 110'))
        marks = []
        if "$" in e["desc"]: marks.append("$ (LaTeX/currency)")
        if "`" in e["desc"]: marks.append("backtick")
        if "[[" in e["desc"]: marks.append("wikilink")
        if re.search(r"\*\*|\*\w[^*]*\*", e["desc"]): marks.append("* (bold/italic)")
        if marks:
            problems.append((sl,"item7",f'description has non-plain-text markup ({", ".join(marks)}) — renders literally in Obsidian Properties'))
        # ---- item 8: tags validity (#-prefixed discipline slugs from the 27-enum; NOT wikilinks) ----
        e_tags_raw, e_tag_slugs = e["tags_raw"], e["tag_slugs"]
        if not e_tags_raw:
            if is_stub:
                problems.append((sl,"item8","stub has blank tags: — every stub needs ≥1 discipline tag, inherited from the entry that links it (wiki-builder's SKILL.md, Stubs (legacy): Structure)"))
            # blank tags: on a FULL entry is valid (no discipline genuinely applies) — not a violation
        for t in e_tags_raw:
            inner = t.strip()
            is_wikilink = inner.startswith("[[") or inner.endswith("]]")
            slugpart = inner.lstrip("#").strip().strip("[]").strip()     # core slug: drop #, [[ ]]
            low = slugpart.lower()
            target = low if low in VALID_TAGS else TAG_ALIASES.get(low)  # the corrected enum slug, if one exists
            faults = []
            if is_wikilink:
                faults.append("written as a wikilink (tags are #-prefixed slugs, not links)")
            elif not inner.startswith("#"):
                faults.append("missing the # prefix (an unquoted # is a YAML comment, silently dropping the discipline)")
            if low not in VALID_TAGS:
                faults.append(f'"{low}" is a known abbreviation/synonym, not an enum slug' if target
                              else f'"{low}" is not one of the 27 discipline slugs')
            elif slugpart != low:
                # The enum slugs are lowercase. A case variant folds onto the
                # right discipline for the census and for Obsidian's search, so
                # nothing downstream broke and nothing reported it either — the
                # entry simply carried a spelling the enum does not contain.
                faults.append(f'"{slugpart}" is a case variant of the enum slug "{low}" '
                              f'(the 27 slugs are lowercase)')
            if faults:
                fix = f'rewrite as "#{target}"' if target else "fix to a valid #-prefixed enum slug"
                problems.append((sl,"item8",f'tag "{t}": ' + "; ".join(faults) + f" — {fix}"))
        # Duplicates are counted on the CANONICAL slug — alias expanded, case
        # folded — not on the raw one. `#ml` beside `#machine-learning` is one
        # discipline written twice, and the raw check reported no duplicate
        # while item 8's own mandated fix above ("rewrite as
        # #machine-learning") went on to create one. Same for `#Machine-Learning`.
        _canon_by_tag = [(t, tag_canonical(s)) for t, s in zip(e_tags_raw, e_tag_slugs)]
        _dup_counts = [c for _t, c in _canon_by_tag]
        for d in sorted({c for c in _dup_counts if _dup_counts.count(c) > 1}):
            spellings = ", ".join(f'"{t}"' for t, c in _canon_by_tag if c == d)
            problems.append((sl,"item8",f'discipline "#{d}" tagged more than once (as {spellings}) — keep one'))
        # ---- item 9: body structure (FULL ENTRIES AND STUBS) ----
        # A stub is exempt from item 9's LENGTH guidance only, not from item 9 wholesale: wiki-builder's
        # stub format is a prose sentence on the line straight after the frontmatter, and its Person/Event
        # stubs carry the date parenthetical after the bolded subject "following the same discipline as full
        # entries" (wiki-builder's SKILL.md, Stubs (legacy)). None of the three checks below is a length check, so all three run
        # on stubs too — this block used to sit behind `if not is_stub:`, which dropped rules the stub format
        # requires.
        if e["blank_after"]:
            problems.append((sl,"item9","blank line immediately after frontmatter"))
        bstrip = e["body"].lstrip()
        if bstrip[:2] in ("##","- ","* ","> ") or bstrip[:1] == "#":
            problems.append((sl,"item9","body does not open with a prose sentence"))
        if e["type"] in ("Person","Event"):
            opener = e["prose"].split("\n\n",1)[0]
            if not re.search(r"\([^)]*\b\d{3,4}\b[^)]*\)", opener):
                problems.append((sl,"item9",f'{e["type"]} opener missing parenthetical date(s)'))
        # ---- item 12 (format): unescaped literal $ and remote image embeds ----
        if not is_stub:
            nd = leftover_dollars(e["body"])
            if nd:
                problems.append((sl,"item12",f'{nd} unescaped literal "$" in body — escape as \\$ (a lone $ renders as math; a $ in a URL needs the image localized)'))
            # Remote ![](http…) embeds are REPORT-ONLY, not a violation. wiki-builder MANDATES this exact
            # form for an external URL coming from a markdown source's clipping ("use standard markdown
            # image syntax ![alt](https://...) since wikilinks don't handle remote URLs" —
            # wiki-builder references/media.md), because an Obsidian wikilink cannot address a remote URL.
            # Filing it as an ordinary itemN problem made the linter "fix in place" a working image into
            # ![[Sources/Images/…]] — a path form wiki-builder does not use either (it embeds a BARE basename,
            # ![[Name_fig_3.png]]) — which resolves to nothing and throws the URL away. Its own item key
            # routes it to the run report instead. DO NOT re-file this as item12.
            for url in REMOTE_IMG.findall(e["body"]):
                problems.append((sl,"item12/remote-image",f'remote image embed ![]({url[:50]}…) — VALID, DO NOT REWRITE (wiki-builder mandates markdown syntax for remote URLs); report only, as a candidate for localizing by re-running clipping-processor on the source clipping'))
            # image embeds need an italic *caption* on the very next line (Captions rule); the caption is plain text
            blines = e["body"].split("\n")
            for i,ln in enumerate(blines):
                if not EMB.match(ln): continue
                cap = blines[i+1].strip() if i+1 < len(blines) else ""
                if not (cap.startswith("*") and not cap.startswith("**") and cap.endswith("*") and len(cap) >= 3):
                    problems.append((sl,"item12",f'image embed without an italic *caption* on the next line: {ln.strip()[:48]}'))
                else:
                    inner = cap.strip("*")
                    cbad = [n for n,c in (("wikilink","[["),("bold","**"),("backtick","`")) if c in inner]
                    if re.search(r"\*\w[^*]*\*", inner): cbad.append("italic")
                    if cbad:
                        problems.append((sl,"item12",f'caption has {", ".join(cbad)} — captions are plain text (only LaTeX $…$ allowed): {cap[:48]}'))
        # ---- item 12 (embeds): every ![[…]] image names a file that is there ----
        # Only with --images: without the folder there is nothing to compare
        # against, and guessing would report every embed in the vault as broken.
        # Outside the `if not is_stub:` block above on purpose — a dead embed is
        # dead whatever the entry is, and item 12's stub exemption is about the
        # figure-and-caption rules a stub has no occasion to break.
        # Read fenced-stripped: an embed shown in a listing is a sample of embed
        # syntax, and Obsidian renders it literally rather than resolving it.
        if img_fold is not None:
            for _m in IMG_EMBED.finditer(strip_fenced(e["body"])):
                # Obsidian resolves an embed by BASENAME vault-wide, so a
                # path-qualified `![[Sources/Images/X.png]]` names the same file
                # as a bare `![[X.png]]` and must not read as missing.
                _img = _m.group(1).strip().replace("\\", "/").rsplit("/", 1)[-1]
                if fold_name(_img) in img_fold:
                    continue
                problems.append((sl,"item12/missing-image",
                                 f'embed names a file that is not in the image folder: {_img} '
                                 f'(Obsidian renders this as plain text, silently) — REPORT '
                                 f'ONLY, DO NOT DELETE THE EMBED OR ITS CAPTION. There are two '
                                 f'repairs and neither is the linter\'s: the figure was never '
                                 f'extracted (run pdf-figure-extractor on the source), or an '
                                 f'approved source rename renamed it with the source '
                                 f'(CONVENTIONS §1a), in which case the embed is rewritten to '
                                 f'the new stem. Deleting the embed throws away the one record '
                                 f'of which figure belongs here'))
        # ---- item 16: body-opener bold vs title — compare skeletons, tolerating LaTeX in the bold and a disambiguation parenthetical in the title ----
        if not is_stub:
            opener = e["prose"].split("\n\n",1)[0]
            mo = re.search(r"\*\*([^*]+)\*\*", opener)
            # The PRESENCE half: an opener with no bold span at all used to be
            # silent (the coherence check below is gated on a bold to compare),
            # so the one entry that skipped the bold entirely was the one
            # entry item 16 never flagged.
            if not mo and opener.strip():
                problems.append((sl,"item16","body opener has no bold span — "
                                             "the opener bolds the entry title "
                                             "on first appearance"))
            if mo and title:
                b = mo.group(1).strip()
                def _dex(s):                                  # strip LaTeX wrappers to a comparable text skeleton
                    s = re.sub(r"\\(?:boldsymbol|mathbf|mathrm|mathit|text)\s*\{([^}]*)\}", r"\1", s)
                    s = s.replace("$","").replace("\\","").replace("{","").replace("}","")
                    return re.sub(r"\s+"," ", s).strip()
                t_norm = re.sub(r"\s*\([^)]*\)\s*$", "", title).strip()   # drop a trailing disambiguation parenthetical
                bb, tt = _dex(b), _dex(t_norm)
                if bb and tt and (bb[:1].lower()+bb[1:] != tt[:1].lower()+tt[1:]):
                    problems.append((sl,"item16",f'body opener "**{b}**" ≠ title "{title}" (after dropping LaTeX wrappers and a disambiguation parenthetical)'))
        # ---- item 16b: unenumerated bold — only title-first-mention, `- **Term** —` anchor, **Related:** ----
        tnorm = (title[:1].lower()+title[1:]) if title else ""
        in_opener = True; opener_skipped = False
        for ln in e["prose"].split("\n"):
            if in_opener and ln.strip() == "": in_opener = False   # opener = the first paragraph
            if re.match(r"^\s*\|", ln):                            # table row: bold/italic permitted in cells
                continue
            if re.match(r"^\s*\*(?!\*).*\*\s*$", ln):              # caption line (whole-line italic) — item-12 owns it
                continue
            # bullet term-anchor line: legit. The bolded anchor may be followed by a short parenthetical or
            # bracketed qualifier (optionally italicized) before the delimiter — wiki-builder's own canonical
            # definition bullet is `- **True positives** (TP) — positives correctly predicted as positive`,
            # which a dash-must-follow-the-`**` pattern wrongly flagged as unenumerated bold (and wiki-builder
            # re-emitted it every run). Prose after the anchor with no delimiter is still flagged.
            if re.match(r"^\s*[-*]\s+\*\*[^*\n]+\*\*(?:\s*[*_]?[\(\[][^)\]\n]{1,60}[\)\]][*_]?)*\s*[—–:\-]", ln):
                continue
            for sp in re.findall(r"\*\*([^*\n]+)\*\*", ln):
                if in_opener and not opener_skipped:               # opener's title slot — item 16 owns its form
                    opener_skipped = True; continue
                spn = sp.strip()
                if not spn or spn == "Related:":
                    continue
                if re.fullmatch(r"\[\[[^\]]*\]\]|\$[^$]+\$|`[^`]+`", spn):   # emphasis around a single wikilink/math/code → emphasis-misuse check owns it
                    continue
                if title and (spn[:1].lower()+spn[1:]) == tnorm:   # a later title bold (Pattern 1 first-mention)
                    continue
                problems.append((sl,"item16",f'unenumerated bold "**{spn}**" — bold is only for the title, `- **Term** (qualifier) —` bullet anchors, and **Related:** (use italics or a wikilink)'))
        # ---- item 16: emphasis (bold/italic) around a wikilink/math/code span — the markup itself is the styling ----
        for m in re.finditer(r"(\*\*|\*)(\[\[[^\]\n]*\]\]|\$[^$\n]+\$|`[^`\n]+`)(\*\*|\*)", e["prose"]+"\n"+e["rel"]):
            if m.group(1) != m.group(3): continue              # require balanced ** ** or * *
            inner = m.group(2)
            kind, fix = ("wikilink","the link") if inner.startswith("[[") else (("math","LaTeX") if inner.startswith("$") else ("code","backticks"))
            problems.append((sl,"item16",f'{"bold" if m.group(1)=="**" else "italic"} around a {kind} ({inner[:30]}) — remove the emphasis; {fix} already provides the styling'))
        # ---- item 13: stray frontmatter key mid-body (stacked-merge scar) ----
        # `importance` stays in this alternation on purpose: it is a legacy key, so a legacy
        # entry's stacked-merge scar can still be an `importance:` line stranded in the body.
        # That is an item-13 structural scar, not an importance rule — there is no item-20 check.
        # Fenced code is masked first. A `Software` entry legitimately SHOWS
        # YAML/config in a listing (`type: Software`, `tags: [...]`), and a
        # scar-detector that reads a listing as a scar told the linter to
        # delete a line out of the entry's own example — the one place in this
        # scan where the fix is destructive and the finding was always false.
        # item 6 keeps its own unmasked view: there, the fence IS the finding.
        # `read` is in this alternation like every other schema key: `read:` is
        # the schema's LAST key, so a partial stacked-merge scar plausibly
        # leaves exactly a `read: false` line — omitting it made qc-items'
        # "any schema key" claim false for the likeliest single-line scar.
        if re.search(r"(?m)^(title|type|aliases|sources|created|updated|description|tags|importance|parents|read):",
                     strip_fenced(e["body"])):
            problems.append((sl,"item13","stray frontmatter key in the body — stacked-merge scar; remove it"))
        # ---- item 19: Flashcards presence/absence + one-card cap + per-card structure / markup / answer-leak ----
        if not is_stub and not e["has_flashcards"]:
            problems.append((sl,"item19","full entry missing ## Flashcards section"))
        if is_stub and e["has_flashcards"]:
            problems.append((sl,"item19","stub has a ## Flashcards section"))
        if not is_stub and e["has_flashcards"]:
            # A tolerated heading spelling (### level, extra/leading spaces) is a
            # PRESENT section with a heading to fix — never a missing section,
            # whose remedy would add a second one beside the section Obsidian
            # already renders.
            if not _FLASH_HEAD_CANON.match(e["flash_head"]):
                problems.append((sl,"item19",f'Flashcards heading spelled "{e["flash_head"].strip()[:30]}" — '
                                             f'the canonical heading is exactly "## Flashcards"; fix the '
                                             f'heading in place, do NOT add a second section'))
            # the ## Flashcards heading must sit under a '---' separator line on its own
            pre = e["body"][:e["flash_off"]].rstrip()
            pre_nb = [l for l in pre.split("\n") if l.strip()]
            if not pre_nb or pre_nb[-1].strip() != "---":
                problems.append((sl,"item19","## Flashcards not preceded by a '---' separator line on its own (Body Structure → Flashcards)"))
            # split the section (after the heading) into card blocks on blank-line boundaries
            after_head = e["fcsec"].split("\n",1)[1] if "\n" in e["fcsec"] else ""
            # Line-4+ HTML comments belong to the review plugin. A blank line
            # inside or between its comments is not another card whose removal
            # may be proposed. Mask comments only in this read-only check.
            after_head = re.sub(r"<!--.*?(?:-->|\Z)", "", after_head, flags=re.S)
            cards = [b for b in re.split(r"\n[ \t]*\n", after_head.strip("\n")) if b.strip()]
            if not cards:
                problems.append((sl,"item19","## Flashcards section has no card"))
            elif len(cards) > 1:
                problems.append((sl,"item19",f'{len(cards)} cards in ## Flashcards — exactly one card per entry; keep the card whose line 3 matches the title (the BASE term, for a parenthetical-disambiguated title), split or drop the rest'))
            alias_forms = [x for a in e["aliases"] for x in (a, a.replace("-"," "))]
            for ci, block in enumerate(cards, 1):
                cl = block.split("\n")
                tag = (f"card {ci}" if len(cards) > 1 else "flashcard")
                if len(cl) < 3:
                    problems.append((sl,"item19",f'{tag} malformed — needs 3 contiguous lines (definition / ?? / term), found {len(cl)} (a blank line between lines 1–3 breaks the card)'))
                    continue
                line1, line2, line3 = cl[0], cl[1].strip(), cl[2]
                if line2 not in ("??","!!"):
                    problems.append((sl,"item19",f'{tag} line 2 is "{line2[:20]}", must be exactly ?? (or !! if the user disabled the card)'))
                l1 = []                              # line 1 takes LaTeX only
                if "[[" in line1: l1.append("wikilink")
                if "`" in line1: l1.append("backtick")
                if "**" in line1: l1.append("bold")
                elif re.search(r"\*\w[^*]*\*", line1): l1.append("italic")
                if l1:
                    problems.append((sl,"item19",f'{tag} line 1 has {", ".join(l1)} — line 1 takes LaTeX only (no wikilinks/bold/italic/backticks)'))
                # leak check: line 1 must not contain THIS card's answer — its own line-3 term (+ parenthetical
                # expansion); add the entry's aliases only when this card's term is the entry title (the primary
                # card). A secondary card legitimately names the primary entity, so don't test it against the title.
                mt = re.match(r"^(.*?)\s*(?:\(([^)]*)\))?\s*$", line3.strip())
                term_main = (mt.group(1) if mt else line3).strip()
                paren = mt.group(2).strip() if (mt and mt.group(2)) else ""
                # the parenthetical is a leak candidate only when it is a real acronym/expansion of the term; a
                # discipline-disambiguation parenthetical ("Model (machine learning)") is just a domain tag, not part
                # of the recall answer, so its appearance in line 1 ("a machine learning system") is context, not a leak.
                cands = [term_main] + ([paren] if (paren and slug(paren) not in VALID_TAGS) else [])
                # The primary-card test compares against the title with a trailing
                # discipline-disambiguation parenthetical stripped: the primary
                # card's line 3 is the BASE term for a disambiguated title
                # ("Feature", not "Feature (machine learning)"), so an exact
                # compare skipped the alias needles for exactly the entries that
                # carry them — every disambiguated entry sat in the blind spot.
                _t_full = title.strip().lower() if title else ""
                _t_base = re.sub(r"\s*\([^)]*\)\s*$", "", title).strip().lower() if title else ""
                if title and term_main.lower() in (_t_full, _t_base):
                    cands += alias_forms
                # Both spellings of every candidate: a hyphenated term leaks in
                # its natural spaced spelling too ("fine tuning" for
                # "Fine-tuning").  lint_entry tests both; the two tools must
                # agree (item 19's de-hyphenated substring check).
                _seen_cf = set()
                cands = [c for c in
                         (x for c0 in cands if c0 for x in (c0, c0.replace("-", " ")))
                         if not (c.lower() in _seen_cf or _seen_cf.add(c.lower()))]
                hit = None                           # word-boundary for ≤4-char tokens; substring otherwise
                for c in cands:
                    if not c: continue
                    if len(c) <= 4:
                        if re.search(r"(?<![A-Za-z0-9])"+re.escape(c)+r"(?![A-Za-z0-9])", line1, re.I): hit = c; break
                    elif c.lower() in line1.lower(): hit = c; break
                if hit:
                    problems.append((sl,"item19",f'{tag} line 1 leaks the answer ("{hit}")'))
                l3 = []                              # line 3 (term) is plain text — no markup at all, including LaTeX
                if "[[" in line3: l3.append("wikilink")
                if "`" in line3: l3.append("backtick")
                if "$" in line3: l3.append("$ (LaTeX)")
                if "**" in line3: l3.append("bold")
                elif re.search(r"\*\w[^*]*\*", line3): l3.append("italic")
                if l3:
                    problems.append((sl,"item19",f'{tag} line 3 (term) has {", ".join(l3)} — the term is plain text matching the title verbatim (no markup, including LaTeX)'))
        # ---- stubs have no Related footer ----
        if is_stub and e["has_related"]:
            problems.append((sl,"stub","stub has a **Related:** footer"))
        # ---- item 14: source-meta phrasings (prose only) ----
        META = [r"\bthe paper\b", r"\bthe chapter\b", r"\bthe book\b", r"\bthe article\b",
                r"\bthe authors?\b", r"\bthe source\b",
                r"as (mentioned|discussed|noted|shown|described) (above|below|earlier|previously)"]
        for pat in META:
            if re.search(pat, e["prose"], re.I):
                problems.append((sl,"item14",f'source-meta phrasing /{pat}/')); break
        # ---- item 10: dangling targets; first-occurrence dup within PROSE ----
        # A target that misses every entry exactly but hits one case- or
        # normalization-insensitively is NOT dangling: Obsidian resolves it to
        # that entry on the vault's APFS volume. It gets its own key, because
        # the two fixes are opposites — a dangler is stubbed or dropped, and
        # stubbing THIS one is destructive: on a case-insensitive volume,
        # writing Wiki/<tgt>.md opens the existing case-variant file and
        # replaces a full entry with a one-line stub.
        # Read the entry with its LISTINGS removed -- fenced blocks and inline
        # code spans -- for the reason item 13's own comment gives about the
        # sibling scar check: a fenced block is shown, not asserted. A
        # `[[target-note]]` inside one renders as literal text and links
        # nothing, so calling it dangling prescribes CREATING a file for
        # something the entry only ever displayed as an example of link
        # syntax. The dup scan reads the same masked text: a target shown in a
        # listing and linked once in prose is linked ONCE, and "keep first
        # only" applied to that pair edits the listing or drops the real link.
        _p10, _r10 = strip_code(e["prose"]), strip_code(e["rel"])
        for m in WIKILINK.finditer(_p10 + "\n" + _r10):
            tgt = m.group(1).split("#")[0].split("^")[0].strip()
            if not tgt:
                continue
            # Three forms Obsidian resolves that a bare `tgt in entries` test
            # calls dangling -- and the documented fix for a dangler writes a
            # stub, i.e. over a real file. A path-qualified link
            # (`sub/delta`), an explicit `.md` suffix, and a link to a
            # document rather than an entry (`Doe_Foo_2025.pdf`, the form
            # CONVENTIONS 6/7 blesses in a `sources:` list).
            bare = tgt.replace("\\", "/").rsplit("/", 1)[-1]
            lookup = bare[:-3] if bare.lower().endswith(".md") else bare
            if fold_name(lookup) in ambiguous_files:
                problems.append((sl, "item10/ambiguous",
                                 f'wikilink target "{tgt}" shares a basename with multiple files; '
                                 f'preserve the link, its path, anchor and display text until the '
                                 f'destination is resolved. Report only; never choose a file by walk order'))
                continue
            actual = fold_of.get(fold_name(lookup))
            if actual == lookup:
                continue
            if actual:
                problems.append((sl,"item10/case",
                                 f'wikilink target "{tgt}" matches the entry "{actual}" only case-/'
                                 f'normalization-insensitively — the link resolves in Obsidian, so this '
                                 f'is a FIX IN PLACE (rewrite the link target to "{actual}", preserving '
                                 f'any existing anchor and display label), '
                                 f'NEVER a stub: on the vault\'s case-insensitive volume a stub written '
                                 f'to "{tgt}.md" opens and overwrites "{actual}.md"'))
            elif fold_name(lookup) in on_disk_fold:
                # The file EXISTS but did not parse (item0/item1), or lives in a
                # symlinked subfolder the walk did not enter. Reporting it as a
                # dangler is wrong twice over: the link resolves in Obsidian,
                # and the documented fix -- write a stub at Wiki/<tgt>.md --
                # opens that very file and replaces it with one line.
                problems.append((sl,"item10/unparsed",
                                 f'wikilink target "{tgt}" names a file that is '
                                 f'on disk but could not be parsed as an entry. '
                                 f'The link resolves; fix that file. NEVER stub '
                                 f'this target -- the stub would overwrite it'))
            elif os.path.splitext(bare)[1].lower() in _DOC_EXTS:
                continue
            elif fold_name(lookup) in alias_of:
                # An ALIAS of another entry. Obsidian resolves it, so it is not
                # a dangler -- and the dangler remedy is the destructive one
                # here: a stub at Wiki/<tgt>.md becomes a FILE with that name,
                # a file outranks an alias, and every [[tgt]] in the vault
                # silently stops resolving to the entry that owns the alias and
                # starts resolving to the one-line stub. Nothing downstream
                # reports that as an item-18 clash, so the link is quietly
                # re-pointed at an empty note for good.
                if fold_name(lookup) in ambiguous_aliases:
                    problems.append((sl, "item10/ambiguous",
                                     f'wikilink target "{tgt}" is claimed as an alias by multiple '
                                     f'entries; preserve the link, anchor and display text until its '
                                     f'owner is resolved. Report only; never choose the first alias owner'))
                    continue
                _own_sl, _own_raw = alias_of[fold_name(lookup)]
                _anchor_match = re.search(r"[#^].*", m.group(1))
                _anchor = _anchor_match.group(0) if _anchor_match else ""
                _label = m.group(2) if m.group(2) is not None else tgt
                _replacement = f'[[{_own_sl}{_anchor}|{_label}]]'
                problems.append((sl,"item10/alias",
                                 f'wikilink target "{tgt}" is an alias of the entry '
                                 f'"{_own_sl}" (aliases: "{_own_raw}"), not an entry of its '
                                 f'own — the link RESOLVES in Obsidian. Fix in place: '
                                 f'rewrite to "{_replacement}", never stub it. Stubbing '
                                 f'creates a file that outranks the alias and steals every '
                                 f'"[[{tgt}]]" in the vault away from "{_own_sl}"'))
            else:
                problems.append((sl,"item10/dangling",f'wikilink target "{tgt}" does not resolve'))
        seen = {}
        for m in WIKILINK.finditer(_p10):
            t = m.group(1).split("#")[0].split("^")[0].strip(); seen[t] = seen.get(t,0)+1
        for t,c in seen.items():
            if c > 1: problems.append((sl,"item10/dup",f'"{t}" wikilinked {c}× in prose — keep first only'))
        # ---- item 11: Related footer bare links rendering lowercase ----
        for m in WIKILINK.finditer(e["rel"]):
            tgt, disp = m.group(1).strip(), m.group(2)
            if disp is None:
                tt = entries.get(tgt,{}).get("title","")
                if tt and tt != tt.lower():
                    problems.append((sl,"item11",f'Related footer bare link [[{tgt}]] should be piped to "{tt}"'))

    # ---- item 18: alias collisions + within-entry dup + display-label sanity ----
    alias_owner = {}
    for sl,e in entries.items():
        al = e["aliases"]
        for a in sorted({x for x in al if al.count(x) > 1}):
            problems.append((sl,"item18",f'alias "{a}" listed {al.count(a)}× within this entry'))
        # Case/normalization-variant duplicates WITHIN one entry: by the
        # fold_name doctrine both tools apply cross-entry, "TPR" beside "tpr"
        # is ONE name to Obsidian listed twice — but the raw count above sees
        # two strings and the cross-entry map skips same-entry pairs, so the
        # pair was reported by nobody.  lint_entry counts the same way; the two
        # tools must agree.
        _fold_first = {}
        for a in al:
            _k = fold_name(a)
            if not _k: continue
            if _k in _fold_first and _fold_first[_k] != a:
                problems.append((sl,"item18",
                                 f'aliases "{_fold_first[_k]}" and "{a}" differ only in '
                                 f'case/normalization — one name to Obsidian; keep one'))
            _fold_first.setdefault(_k, a)
        # Keyed on fold_name, like every other "is this the same name?"
        # comparison in this file (see fold_name's docstring). Two aliases that
        # differ only in case or Unicode normalization are ONE name to Obsidian
        # and one file on the vault's APFS volume, so [[Lambda-Rank]] resolves
        # to whichever entry Obsidian picks and the other becomes unreachable
        # under its own alias. Comparing raw strings reported nothing, and
        # CONVENTIONS §9 gives whole-vault dedup to this skill alone, so on a
        # vault-wide run the pair was seen by nobody. The raw spelling is kept
        # for the message: the fix is to change one of the two spellings, and
        # the user has to be told which two they are.
        for a in al:
            k = fold_name(a)
            if k in alias_owner and alias_owner[k][0] != sl:
                own_sl, own_raw = alias_owner[k]
                problems.append((sl,"item18",
                                 f'alias "{a}" also on "{own_sl}"'
                                 + ("" if own_raw == a else
                                    f' (spelled "{own_raw}" there — the two differ only in '
                                    f'case/normalization, which is one name to Obsidian and '
                                    f"one file on the vault's volume)")))
            elif k not in alias_owner:
                alias_owner[k] = (sl, a)
    def _toks(s):                                    # tokens: lowercased, hyphens→spaces, a disambiguation parenthetical dropped
        s = re.sub(r"\s*\([^)]*\)\s*", " ", s.lower())
        return re.findall(r"[a-z0-9]+", s.replace("-", " "))
    def _stem(t):                                     # crude inflection stem: tuning/tuned/tunes/tune -> tun
        for suf in ("ing", "ed", "es", "s"):          # one suffix, longest first; keep >=3 chars of stem
            if t.endswith(suf) and len(t) - len(suf) >= 3:
                t = t[: -len(suf)]; break
        if t.endswith("e") and len(t) >= 4:           # e-drop stems: tune -> tun, so tuned/tuning match tune
            t = t[:-1]
        return t
    def _tok_match(a, b):                             # tolerant of inflection/truncation between a display token and a title token
        # The 4-char common-prefix floor alone misses short e-drop verb stems: "tuned" vs "tuning" share only
        # "tun" (3), so [[fine-tuning|fine-tuned]] false-flagged on a real vault even though the display-label
        # carve-out explicitly permits natural verb inflections. Stems must be EQUAL (not prefixes) so a
        # genuinely different word ("tuner", "transfer") still flags.
        if a in b or b in a or len(os.path.commonprefix([a, b])) >= 4:
            return True
        sa, sb = _stem(a), _stem(b)
        return len(sa) >= 3 and sa == sb
    title_forms = {sl: [_toks(e["title"])] + [_toks(a) for a in e["aliases"]] for sl,e in entries.items()}
    for sl,e in entries.items():
        for m in re.finditer(r"\[\[([^\]|#^]+)(?:[#^][^\]|]*)?\|([^\]\n]+)\]\]", e["prose"]+"\n"+e["rel"]):
            tgt, disp = m.group(1).strip(), m.group(2).strip()
            dmark = []
            if "$" in disp: dmark.append("$ (LaTeX)")
            if "`" in disp: dmark.append("backtick")
            if "**" in disp: dmark.append("** (bold)")
            elif re.search(r"\*\w[^*]*\*", disp): dmark.append("* (italic)")
            if dmark:
                problems.append((sl,"item18",f'wikilink display label "{disp[:40]}" has markup ({", ".join(dmark)}) — labels render as plain text; put math/emphasis in the surrounding prose'))
                continue
            # Display label is valid when, for some title/alias form, the label's tokens are a SUBSET of the form
            # (inflection/truncation tolerant) — this accepts the bare display of a cross-domain qualified link,
            # [[information-entropy|entropy]], which wiki-builder MANDATES and FORBIDS as an alias so it can never be
            # in a surface set — OR a SUPERSET of the form, i.e. the label contains all the form's tokens plus extras,
            # which accepts a more-specific display that prepends a qualifier, [[neural-network|deep neural networks]].
            # An exact-match check false-flagged both (108-of-110 false positives on a real run); "fixing" the bare
            # case by adding the bare alias is exactly the silent cross-domain collision wiki-builder exists to prevent.
            # Do NOT re-tighten to exact match, and do NOT add a single-token-strict-subset guard (re-flags bare terms).
            # Still flags a label that is neither subset nor superset of any form (a wrong target / invented label).
            if tgt in title_forms and disp:
                dt = _toks(disp)
                ok = False
                for form in title_forms[tgt]:
                    if not form: continue
                    sub = all(any(_tok_match(d, t) for t in form) for d in dt)   # label ⊆ form: bare term / inflection
                    sup = all(any(_tok_match(d, t) for d in dt) for t in form)   # label ⊇ form: qualifier-prefixed, more specific
                    if sub or sup: ok = True; break
                if dt and not ok:
                    problems.append((sl,"item18",f'wikilink [[{tgt}|{disp}]] — "{disp}" shares no surface form with "{tgt}" (its title/aliases); likely wrong target or invented label'))

    # ---- item 5: collision probes across entries (REPORT as candidates; merge is the user's call) ----
    collisions = []
    ident_owner = {}                      # exact identifier (slug or alias) -> first owner
    for sl,e in entries.items():
        for ident in [sl] + e["aliases"]:
            if ident in ident_owner and ident_owner[ident] != sl:
                collisions.append((sl, ident_owner[ident], "exact", ident))
            else:
                ident_owner.setdefault(ident, sl)
    def group_probe(keyfn, name, pair_ok=None):
        # `pair_ok(ident_a, ident_b)` is an optional last-word filter on a grouped pair —
        # for a probe whose key deliberately over-groups (see word-order-singular below).
        # `keyfn` may return one key or a SET of them: English singularization is
        # ambiguous ("bases" = base | basis), so an identifier has to be filed under
        # every plausible reading or the probe only fires when the plural happens to
        # be the side that guessed right.
        groups = {}
        for sl,e in entries.items():
            for ident in [sl] + e["aliases"]:
                k = keyfn(ident)
                for key in ((k,) if isinstance(k, str) else k):
                    groups.setdefault(key, set()).add((sl, ident))
        for key,members in groups.items():
            slugs = {m[0] for m in members}
            if len(slugs) > 1:
                ms = sorted(members)
                for i in range(len(ms)):
                    for j in range(i+1,len(ms)):
                        if ms[i][0] != ms[j][0] and (pair_ok is None or pair_ok(ms[i][1], ms[j][1])):
                            collisions.append((ms[i][0], ms[j][0], name, f"{ms[i][1]}~{ms[j][1]}"))
    # `singular_keys` is shared/scripts/plurals.py's probe-(c) key SET — every plausible
    # singular of the identifier's head token, the identifier itself included — so an
    # ambiguous `-es` ("bases" = base + basis) files under both readings in one pass.
    group_probe(singular_keys, "plural")
    group_probe(lambda s: s.replace("-",""), "hyphenation")
    group_probe(lambda s: "-".join(sorted(s.split("-"))), "word-order")
    # The sort above is a PURE token sort, so it cannot see `weight-tying` ~ `tying-weights`:
    # `weights` does not sort to `weight`. wiki-builder/SKILL.md:125 calls the singularization
    # step load-bearing for exactly that pair, and wiki-builder's find_collisions.py runs probe
    # (e) twice for it (`wordorder_key` AND `wordorder_key_singular`). CONVENTIONS §9 gives
    # whole-vault duplicate detection to wiki-linter alone — wiki-builder only probes the
    # candidates of the source in front of it — so a pair already sitting in the vault is seen
    # by NOBODY unless this scanner runs the singularized half too. The key function is
    # shared/scripts/plurals.py's, the same one wiki-builder calls, so there is nothing left
    # here to drift from it.
    #
    # `real_permutation` is that module's guard, not a copy of it: this probe fires only on a
    # GENUINE re-ordering. Equal raw sorts are the `word-order` hit above, and an identical
    # singularized token SEQUENCE is a plain plural pair `plural` already reports — either
    # would put the same pair in the worklist a second time.
    group_probe(wordorder_key_singular, "word-order-singular", real_permutation)
    # µ-variant probe via titles
    for sl,e in entries.items():
        t = e["title"]
        if "µ" in t or "μ" in t:
            alt = slug(t.replace("µ","\u03bc")) if "µ" in t else slug(t.replace("\u03bc","µ"))
            if alt != sl and alt in entries:
                collisions.append((sl, alt, "µ-variant", f"{sl}~{alt}"))
    # dedup collisions (unordered pair + probe)
    seen_c = set(); collisions2 = []
    for a,b,p,d in collisions:
        key = (frozenset((a,b)), p)
        if key in seen_c: continue
        seen_c.add(key); collisions2.append((a,b,p,d))

    # ---- Surface map + backfill candidates (Task 2 worklist; model judges closeness) ----
    surface_owners = {}                   # lowercased surface form -> all owners
    _title_surf, _alias_surf = set(), set()
    for sl,e in entries.items():
        forms = [("title", e["title"])] + [("alias", a.replace("-"," ")) for a in e["aliases"]]
        for kind, f in forms:
            if not f or len(f) < 3: continue
            # `plural_surface`, not `pluralize`: the latter takes ONE token, and
            # a whole title matches no irregular in its table (see plural_surface).
            for variant in (f, plural_surface(f)):
                surface_owners.setdefault(variant.lower(), set()).add(sl)
                (_title_surf if kind == "title" else _alias_surf).add(variant.lower())
    # A shared title/alias (or plural) supplies no unique link destination.
    # Choosing the first owner can link an entry's own opener to another
    # entity; duplicate basenames are ambiguous even with one parsed record.
    surf_map = {surface: next(iter(owners))
                for surface, owners in surface_owners.items()
                if len(owners) == 1
                and fold_name(next(iter(owners))) not in ambiguous_files}
    # Alias-mediated bare-noun surfaces: a single all-lowercase word reached
    # only through an alias ("attribute", "target", "predictor").  These match
    # everywhere, nearly always fail the closeness bar, and — candidates
    # carrying no memory — resurfaced for identical re-judgment every run.
    # The candidate is still emitted (the closeness call stays with the model;
    # a qualified-target link to a bare term is legal in principle) but is
    # TAGGED `bare_noun_alias` so the report can batch them.  The same
    # single-word shape reached through a TITLE is already suppressed or
    # surfaced by COMMON_NOUNS and item 5's bare-slug check.
    bare_noun_alias = {s for s in _alias_surf - _title_surf
                       if re.fullmatch(r"[a-z]+", s)}
    backfill = build_backfill(entries, surf_map)

    stubs = [sl for sl,e in entries.items() if e["is_stub"]]
    fulls = [sl for sl,e in entries.items() if not e["is_stub"]]

    # ---- discipline-tag census (VALID enum slugs vs off-enum/malformed) ----
    tag_counts = {}                       # VALID discipline slug -> [non-stub count, stub count]
    off_enum = {}                         # malformed/off-enum slug -> [entries using it]
    for sl,e in entries.items():
        for d in set(e["tag_slugs"]):
            if d.lower() in VALID_TAGS:
                tag_counts.setdefault(d.lower(), [0,0])
                tag_counts[d.lower()][1 if e["is_stub"] else 0] += 1
            else:
                off_enum.setdefault(d, []).append(sl)
    # blank tags: on a FULL entry is valid — no MOC placement, listed as unplaced
    untagged_full = [sl for sl,e in entries.items()
                     if not e["is_stub"] and not e["tag_slugs"] and "tags" in e["key_order"]]

    # ---- problem tally by checklist item ----
    # The share of entries affected is the recurrence signal for wiki-builder-improvement
    # proposals — see SKILL.md, 'Closing the loop'.
    tally = {}                                   # item -> [issue_count, set_of_entries]
    for sl,item,_ in problems:
        t = tally.setdefault(item, [0, set()])
        t[0] += 1; t[1].add(sl)
    nfull = len(fulls) or 1
    full_set = set(fulls)
    tally_out = [dict(item=item, entries=len(ents), pct_of_full=100*len(ents & full_set)//nfull, issues=cnt)
                 for item,(cnt,ents) in sorted(tally.items(),
                                               key=lambda kv: (-len(kv[1][1]), -kv[1][0], kv[0]))]

    # ---- Rename candidates (item 5): filename != slug(title). PROPOSE for approval — never auto-apply (a rename rewrites links vault-wide). ----
    inbound = {}
    for _e in entries.values():
        for _m in WIKILINK.finditer(_e["prose"] + "\n" + (_e["rel"] or "")):
            _k = _m.group(1).split("#")[0].split("^")[0].strip()
            # count against the on-disk slug the link actually resolves to, so
            # a case-variant inbound link still counts toward the file it opens
            _k = fold_of.get(fold_name(_k), _k)
            inbound[_k] = inbound.get(_k, 0) + 1
    renames = []
    _rename_targets = {}                  # folded new_slug -> [entries proposing it]
    for _sl,_e in sorted(entries.items()):
        _new = slug(_e["title"]) if _e["title"] else ""
        # An unsluggable title (CJK, all-symbol) yields "" — renaming to it produces a
        # file literally called ".md".  Never propose it; item 5 already reports the title.
        if not _new or _new == _sl: continue
        _rename_targets.setdefault(fold_name(_new), []).append(_sl)
        renames.append([_sl, _new, inbound.get(_sl, 0)])
    for _r in renames:
        # target_exists ⇒ likely duplicate/disambiguation; do NOT rename into it, flag both.
        # Compared FOLDED, because the destination is "taken" whenever a file the
        # vault's case-insensitive volume resolves to that name exists — except the
        # entry being renamed itself, whose case-only rename is one file changing
        # its own spelling and is safe. Two candidates aiming at ONE destination
        # counts too: applying both in sequence would have the second silently
        # overwrite the first.
        #
        # `on_disk_fold` is consulted as well as `fold_of`, and for the same
        # reason the item10/unparsed carve-out above consults it: a file that
        # is ON DISK but did not parse (no frontmatter, unreadable) is absent
        # from `entries`, so `fold_of` alone answers "free" for a destination
        # that is a real file. The approved rename is `mv wrong-name.md
        # broken.md`, which destroys it. Both sets are the same question —
        # "does a file already answer to this name?" — and only their union
        # answers it.
        _fold_new = fold_name(_r[1])
        _owner = fold_of.get(_fold_new)
        _r.append((_owner is not None and _owner != _r[0])
                  or _fold_new in on_disk_fold
                  or len(_rename_targets[_fold_new]) > 1)

    # ---- Hierarchy diagnostic (Task 3): how many full entries currently self-parent? ----
    # Reflects the EXISTING parents: from a prior run (blank on a never-linted vault). Under the MOC-root rule every
    # tree is rooted at the discipline's own MOC note, so NOTHING self-parents and the correct count is zero: every
    # slug reported here is stale parents: from a pre-MOC-root run or a hand-edit, which this run overwrites. That is
    # why check_rooting fires at >=1 — the old >=3 was the anchor-entry model's tolerance for ~1 legitimate root per
    # discipline, and there are no legitimate self-parents left to tolerate. See Task 3 / references/hierarchy.md.
    def _parent_targets(e):
        out = []
        for p in e.get("parents", []):
            m = re.match(r"\s*\[\[([^\]|#]+)", str(p))
            if not m:
                continue
            target = m.group(1).split("^", 1)[0].strip()
            target = target.replace("\\", "/").rsplit("/", 1)[-1]
            if target.lower().endswith(".md"):
                target = target[:-3]
            if target:
                out.append(target)
        return out
    def _self_parent(e):
        return fold_name(e["slug"]) in {fold_name(t) for t in _parent_targets(e)}
    selfp = sorted(sl for sl,e in entries.items() if not e["is_stub"] and _self_parent(e))
    # ---- parent CYCLES of length >= 2 (Task 3) ----
    # A self-parent is the 1-cycle and is reported above.  The 2-cycle — A
    # parents B and B parents A — is the one a hand-edit or an interrupted run
    # actually leaves behind, and it was invisible: nothing self-parented, the
    # diagnostic read clean, and every walk up the tree from either entry runs
    # forever.  Longer cycles come out of the same search for free.
    _parent_of = {}
    for _sl, _e in entries.items():
        _parent_of[_sl] = [fold_of.get(fold_name(t), t) for t in _parent_targets(_e)]
    # One depth-first walk with three-colour marking, so every EDGE is looked at
    # once and the pass is O(entries + parent links). Enumerating every simple
    # cycle instead is exponential on a densely mis-parented vault, and this is
    # a diagnostic: one cycle per back edge is what Task 3 needs to break it.
    _state = {}                       # slug -> 1 on the current path, 2 finished
    _cycles, _seen_cyc = [], set()
    for _start in sorted(entries):
        if _state.get(_start):
            continue
        _state[_start] = 1
        _path = [_start]
        _stack = [(_start, iter(sorted(_parent_of.get(_start, []))))]
        while _stack:
            _node, _it = _stack[-1]
            _nxt = next(_it, None)
            if _nxt is None:
                _state[_node] = 2
                _stack.pop(); _path.pop()
                continue
            if _nxt not in entries:            # a dangling parent: item10 owns it
                continue
            if _state.get(_nxt) == 1:          # a back edge, i.e. a cycle
                _cyc = _path[_path.index(_nxt):]
                if len(_cyc) < 2: continue     # the 1-cycle is `self_parented`
                _i = _cyc.index(min(_cyc))     # rotate to a canonical spelling
                _rot = tuple(_cyc[_i:] + _cyc[:_i])
                if _rot not in _seen_cyc:
                    _seen_cyc.add(_rot); _cycles.append(list(_rot))
                continue
            if _state.get(_nxt) == 2:
                continue
            _state[_nxt] = 1
            _path.append(_nxt)
            _stack.append((_nxt, iter(sorted(_parent_of.get(_nxt, [])))))
    _cycles.sort()
    per_disc, full_per_disc = {}, {}
    for sl,e in entries.items():
        if e["is_stub"]: continue
        for d in e["tag_slugs"]:
            full_per_disc[d] = full_per_disc.get(d,0) + 1
            if sl in selfp: per_disc[d] = per_disc.get(d,0) + 1

    return {
        # stamp the suggestion-log appends with this
        "run_timestamp": f"{datetime.datetime.now():%Y-%m-%d %H:%M}",
        "wiki_path": os.path.abspath(wiki),
        "inventory": {
            "entries": len(entries),
            "full": len(fulls),
            "stubs": len(stubs),
            "full_slugs": sorted(fulls),
            "stub_slugs": sorted(stubs),
        },
        "discipline_tags": {d: {"full": c[0], "stub": c[1]} for d,c in sorted(tag_counts.items())},
        "off_enum_tags": {d: sorted(set(v)) for d,v in sorted(off_enum.items())},
        "untagged_full": sorted(untagged_full),
        "problems": [{"slug": s, "item": i, "message": m} for s,i,m in sorted(problems)],
        "problem_tally": tally_out,
        "collision_candidates": [{"a": a, "b": b, "probe": p, "detail": d}
                                 for a,b,p,d in sorted(collisions2)],
        "rename_candidates": [{"slug": s, "new_slug": n, "inbound_links": c, "target_exists": x}
                              for s,n,c,x in sorted(renames)],
        # `bare_noun_alias`: the matched surface is a single all-lowercase word
        # reached only through an alias — batch these in the report; the
        # closeness judgment itself stays with the model (see build_backfill).
        "backfill_candidates": [{"slug": s, "target": t, "surface": f,
                                 "bare_noun_alias": key in bare_noun_alias}
                                for s,t,f,key in sorted(backfill)],
        "hierarchy_diagnostic": {
            "full_entries": len(fulls),
            "self_parented": selfp,
            # Cycles of length >= 2 in `parents:` (the 1-cycle is `self_parented`).
            # Each is listed once, rotated to start at its alphabetically first
            # slug. Any entry named here has no path to a MOC root, so Task 3
            # must break the cycle before it can place either end.
            "parent_cycles": _cycles,
            "per_discipline": [{"discipline": d,
                                "self_parent": per_disc[d],
                                "full": full_per_disc.get(d, 0),
                                "check_rooting": per_disc[d] >= 1}   # trees root at the discipline MOC, so ANY self-parent is stale
                               for d in sorted(per_disc)],
        },
    }


# ===========================================================================
# self-test
# ===========================================================================
#
# This scanner drives IN-PLACE EDITS to a whole vault, and several of its
# findings prescribe writing a file: an `item10/dangling` is stubbed, which
# means creating `Wiki/<target>.md`.  Every case below is one where being
# wrong costs a file -- a link mis-classified as dangling whose "fix" opens
# and truncates a real entry, a duplicate tag certified absent whose mandated
# fix then creates it, a backfill proposal aimed at a line no link may be
# written on.  Fixtures are built under `tempfile` and deleted; nothing here
# reads or writes anything outside the temp directory.
#
#     python3 scan_vault.py --test

def _st_entry(title, prose, tags=('"#statistics"',), type_="Concept",
              sources=('"[[Doe_X_2025.pdf#page=2]]"',), aliases=(),
              parents=(), extra_keys="", card=None, related=None):
    """A schema-clean full entry, so a case only carries the fault it names.

    Anything left at its default produces NO finding -- the `clean entry`
    case below asserts exactly that -- so a case that adds one fault gets one
    finding, and a check that fires on the scaffolding is caught immediately.
    """
    def _block(key, items):
        if not items:
            return "%s: []\n" % key
        return "%s:\n" % key + "".join("  - %s\n" % i for i in items)
    fm = ['title: "%s"' % title, "type: %s" % type_]
    text = fm[0] + "\n" + fm[1] + "\n"
    if aliases:
        text += _block("aliases", aliases)
    text += _block("sources", sources)
    text += "created: 2026-01-01\nupdated: 2026-01-02\n"
    text += 'description: "A worked example used by the self-test."\n'
    text += _block("tags", tags)
    text += extra_keys
    text += _block("parents", parents)
    text += "read: false\n"
    body = prose
    if related:
        body += "\n\n**Related:** " + related
    if card is not False:
        term = card or title
        body += ("\n\n---\n\n## Flashcards\n\n"
                 "The idea this entry is about, stated once.\n??\n%s\n" % term)
    return "---\n" + text + "---\n" + body + "\n"


def _st_write(root, relpath, text, encoding="utf-8"):
    path = os.path.join(root, *relpath.split("/"))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    mode, kw = ("wb", {}) if isinstance(text, bytes) else ("w", {"encoding": encoding})
    with open(path, mode, **kw) as fh:
        fh.write(text)
    return path


def _st_items(res, slug=None):
    """The (slug, item) pairs reported, optionally for one entry."""
    return sorted((p["slug"], p["item"]) for p in res["problems"]
                  if slug is None or p["slug"] == slug)


def _st_keys(res, slug):
    return sorted(p["item"] for p in res["problems"] if p["slug"] == slug)


def _st_msg(res, slug, item):
    return " | ".join(p["message"] for p in res["problems"]
                      if p["slug"] == slug and p["item"] == item)


def run_self_test():
    import contextlib
    import io
    from pathlib import Path
    import shutil
    import tempfile
    cases = []

    def check(label, got, want):
        cases.append((label, got == want, got, want))

    tmp = tempfile.mkdtemp(prefix="scan_vault-selftest-")
    try:
        # ------------------------------------------------------------------
        # 1. parsing: what becomes an entry, and what becomes a report
        # ------------------------------------------------------------------
        v = os.path.join(tmp, "v1")
        _st_write(v, "anchor.md", _st_entry("Anchor", "**Anchor** is a worked example."))
        _st_write(v, "no-fm.md", "no frontmatter at all, just prose\n")
        _st_write(v, "unterminated.md",
                  '---\ntitle: "Unterminated"\ntype: Concept\nnever closed\n')
        # a byte that is not valid UTF-8: read() raises, and one bad file must
        # not take the scan down with it
        _st_write(v, "binary.md", b'---\ntitle: "Caf\xe9"\n---\nbody\n')
        _st_write(v, "bom.md", "\ufeff" + _st_entry("Bom", "**Bom** is a worked example."))
        _st_write(v, "crlf.md",
                  _st_entry("Crlf", "**Crlf** is a worked example.").replace("\n", "\r\n"))
        _st_write(v, "crlf-blank.md",
                  _st_entry("Crlf blank", "**Crlf blank** is a worked example.")
                  .replace("---\n**Crlf blank**", "---\n\n**Crlf blank**")
                  .replace("\n", "\r\n"))
        _st_write(v, "stubby.md", _st_entry(
            "Stubby", "**Stubby** is a placeholder.", sources=('"stub"',), card=False))
        _st_write(v, "sub/nested.md",
                  _st_entry("Nested", "**Nested** is a worked example."))
        # a leading blank line: Obsidian reads properties only at line 1
        _st_write(v, "leading-blank.md", "\n" + _st_entry(
            "Leading blank", "**Leading blank** is a worked example."))
        # a frontmatter line that is neither a key nor a list item
        _st_write(v, "stray-line.md",
                  _st_entry("Stray line", "**Stray line** is a worked example.")
                  .replace("type: Concept\n",
                           "type: Concept\nnot a key or a list item\n"))
        linked = os.path.join(tmp, "linked-target")
        os.makedirs(linked)
        _st_write(linked, "symlinked.md",
                  _st_entry("Symlinked", "**Symlinked** is a worked example."))
        have_symlink = True
        try:
            os.symlink(linked, os.path.join(v, "linkdir"))
        except (OSError, NotImplementedError, AttributeError):
            have_symlink = False
        res = scan(v)

        check("a schema-clean entry produces no finding at all",
              _st_keys(res, "anchor"), [])
        check("...and is parsed into the inventory",
              res["inventory"]["full"] >= 1 and "anchor" in res["inventory"]["full_slugs"],
              True)
        check("no frontmatter -> item1", _st_keys(res, "no-fm"), ["item1"])
        check("an unterminated --- fence is not frontmatter -> item1",
              _st_keys(res, "unterminated"), ["item1"])
        check("a file that is not UTF-8 -> item0, and the scan continues",
              _st_keys(res, "binary"), ["item0"])
        check("a BOM does not hide the frontmatter", _st_keys(res, "bom"), [])
        check("a LEADING BLANK LINE before the fence is no frontmatter -> "
              "item1 (Obsidian reads properties only at line 1)",
              _st_keys(res, "leading-blank"), ["item1"])
        check("a frontmatter line that is neither key nor item is item1, "
              "never silently dropped",
              (_st_keys(res, "stray-line"),
               "not a key or a list item" in _st_msg(res, "stray-line", "item1")),
              (["item1"], True))
        check("CRLF line endings parse", _st_keys(res, "crlf"), [])
        check("...and a CRLF blank line after the frontmatter is still item9",
              _st_keys(res, "crlf-blank"), ["item9"])
        check("sources: [\"stub\"] is a stub",
              res["inventory"]["stub_slugs"], ["stubby"])
        check("an entry in a subfolder is scanned", "nested" in res["inventory"]["full_slugs"], True)
        if have_symlink:
            check("an entry in a SYMLINKED subfolder is scanned",
                  "symlinked" in res["inventory"]["full_slugs"], True)
        check("every entry in the fixture is accounted for (the four "
              "unparseable files are reported, not counted)",
              res["inventory"]["entries"], 7 + (1 if have_symlink else 0))

        # zero entries, and one entry
        empty = os.path.join(tmp, "empty")
        os.makedirs(empty)
        res0 = scan(empty)
        check("an empty vault scans to zero entries and zero problems",
              (res0["inventory"]["entries"], res0["problems"],
               res0["backfill_candidates"], res0["collision_candidates"]),
              (0, [], [], []))
        one = os.path.join(tmp, "one")
        _st_write(one, "solo.md", _st_entry("Solo", "**Solo** is a worked example."))
        res1 = scan(one)
        check("a one-entry vault scans clean",
              (res1["inventory"]["entries"], res1["inventory"]["full"],
               res1["problems"]), (1, 1, []))

        # ------------------------------------------------------------------
        # 2. item 10 -- the destructive one.  A target mis-called `dangling`
        #    gets a stub written AT it, so every carve-out below is a file.
        # ------------------------------------------------------------------
        v = os.path.join(tmp, "v2")
        _st_write(v, "sub/delta.md", _st_entry("Delta", "**Delta** is a worked example."))
        _st_write(v, "ROC-curve.md", _st_entry("ROC-curve", "**ROC-curve** is a worked example."))
        _st_write(v, "broken.md", "no frontmatter here either\n")
        _st_write(v, "hub.md", _st_entry(
            "Hub",
            "**Hub** is a worked example that links to [[nowhere]], to "
            "[[roc-curve]], to [[broken]], to [[sub/delta]], to [[delta.md]], "
            "to [[Doe_Foo_2025.pdf]] and embeds ![[figure.png]].\n\n"
            "It also links [[sub/delta]] a second time."))
        res = scan(v)
        got = sorted(set(k for k in _st_keys(res, "hub")))
        check("a genuine dangler is item10/dangling", "item10/dangling" in got, True)
        check("...and only the genuine one",
              _st_msg(res, "hub", "item10/dangling").count("does not resolve"), 1)
        check("a case-only mismatch is item10/case, never a dangler",
              "nowhere" in _st_msg(res, "hub", "item10/dangling")
              and "roc-curve" in _st_msg(res, "hub", "item10/case"), True)
        check("a target on disk that did NOT parse is item10/unparsed, not dangling",
              "broken" in _st_msg(res, "hub", "item10/unparsed"), True)
        check("...and item10/unparsed says never to stub it",
              "NEVER stub" in _st_msg(res, "hub", "item10/unparsed"), True)
        check("a path-qualified target resolves",
              "sub/delta" in _st_msg(res, "hub", "item10/dangling"), False)
        check("an explicit .md suffix resolves",
              "delta.md" in _st_msg(res, "hub", "item10/dangling"), False)
        check("a document link (.pdf) is not an entry link",
              "Doe_Foo_2025.pdf" in _st_msg(res, "hub", "item10/dangling"), False)
        check("an ![[image.png]] embed is excluded from item 10 entirely",
              "figure.png" in " ".join(p["message"] for p in res["problems"]), False)
        check("the same target twice in prose is item10/dup",
              "sub/delta" in _st_msg(res, "hub", "item10/dup"), True)

        # ------------------------------------------------------------------
        # 3. item 8 -- tag aliases, case variants, and the duplicate check
        # ------------------------------------------------------------------
        v = os.path.join(tmp, "v3")
        _st_write(v, "aliased.md", _st_entry(
            "Aliased", "**Aliased** is a worked example.",
            tags=('"#ml"', '"#machine-learning"')))
        _st_write(v, "abbrev.md", _st_entry(
            "Abbrev", "**Abbrev** is a worked example.", tags=('"#ml"',)))
        _st_write(v, "cased.md", _st_entry(
            "Cased", "**Cased** is a worked example.", tags=('"#Machine-Learning"',)))
        _st_write(v, "twice.md", _st_entry(
            "Twice", "**Twice** is a worked example.",
            tags=('"#statistics"', '"#statistics"')))
        _st_write(v, "offenum.md", _st_entry(
            "Offenum", "**Offenum** is a worked example.", tags=('"#astrology"',)))
        _st_write(v, "twocards.md", _st_entry(
            "Twocards", "**Twocards** is a worked example.",
            tags=('"#physics"',)).replace(
            "??\nTwocards\n",
            "??\nTwocards\n\nAnother notion, stated briefly.\n??\nSecond idea\n"))
        res = scan(v)
        check("#ml is reported as an abbreviation with its expansion named",
              'rewrite as "#machine-learning"' in _st_msg(res, "abbrev", "item8"), True)
        check("...and on its own it is NOT a duplicate",
              "tagged more than once" in _st_msg(res, "abbrev", "item8"), False)
        check("#ml beside #machine-learning IS a duplicate (item 8's own fix "
              "creates it otherwise)",
              "tagged more than once" in _st_msg(res, "aliased", "item8"), True)
        check("...and the duplicate message names both spellings",
              '"#ml"' in _st_msg(res, "aliased", "item8")
              and '"#machine-learning"' in _st_msg(res, "aliased", "item8"), True)
        check("a case variant of an enum slug is reported",
              "case variant" in _st_msg(res, "cased", "item8"), True)
        check("...with the lowercase enum slug as the fix",
              'rewrite as "#machine-learning"' in _st_msg(res, "cased", "item8"), True)
        check("an exact duplicate tag is still a duplicate",
              "tagged more than once" in _st_msg(res, "twice", "item8"), True)
        check("...and every duplicate names the CANONICAL discipline, not the "
              "raw spelling",
              (('discipline "#machine-learning" tagged more than once'
                in _st_msg(res, "aliased", "item8")),
               ('discipline "#statistics" tagged more than once'
                in _st_msg(res, "twice", "item8"))), (True, True))
        check("tag_canonical expands an alias and folds case, and leaves an "
              "off-enum slug alone",
              [tag_canonical(t) for t in ("ml", "Machine-Learning",
                                          "machine-learning", "astrology")],
              ["machine-learning", "machine-learning", "machine-learning",
               "astrology"])
        check("an off-enum tag is reported and lands in off_enum_tags",
              ("not one of the 27" in _st_msg(res, "offenum", "item8"),
               sorted(res["off_enum_tags"])), (True, ["astrology", "ml"]))
        check("the tag census counts the enum tags",
              res["discipline_tags"].get("statistics", {}).get("full"), 1)
        check("a second flashcard trips the one-card cap",
              "exactly one card per entry" in _st_msg(res, "twocards", "item19"), True)

        # ------------------------------------------------------------------
        # 4. near-duplicate surfaces + the backfill worklist
        # ------------------------------------------------------------------
        check("plural_surface inflects the HEAD token, not the whole title",
              [plural_surface(t) for t in
               ("Confusion matrix", "Hypothesis", "ROC curve", "Analysis")],
              ["Confusion matrices", "Hypotheses", "ROC curves", "Analyses"])
        v = os.path.join(tmp, "v4")
        _st_write(v, "confusion-matrix.md",
                  _st_entry("Confusion matrix", "**Confusion matrix** is a worked example.",
                            card="Confusion matrix"))
        _st_write(v, "hypothesis.md",
                  _st_entry("Hypothesis", "**Hypothesis** is a worked example.",
                            card="Hypothesis"))
        _st_write(v, "mentions.md", _st_entry(
            "Mentions",
            "**Mentions** is a worked example. Several confusion matrices are "
            "compared, and competing hypotheses are listed."))
        _st_write(v, "unlinkable.md", _st_entry(
            "Unlinkable",
            "**Unlinkable** is a worked example with nothing linkable in prose.\n\n"
            "| Metric | Note |\n|---|---|\n| Confusion matrix | inside a table cell |\n\n"
            "```\nConfusion matrix inside a fenced listing\n```\n\n"
            "![[figure.png]]\n*A confusion matrix, in a caption.*"))
        _st_write(v, "already.md", _st_entry(
            "Already",
            "**Already** is a worked example that already links "
            "[[confusion-matrix|Confusion matrix]] once, and names confusion "
            "matrices again in bare text afterwards."))
        res = scan(v)
        pairs = sorted((b["slug"], b["target"]) for b in res["backfill_candidates"])
        check("an irregular plural in prose is a backfill candidate",
              ("mentions", "confusion-matrix") in pairs
              and ("mentions", "hypothesis") in pairs, True)
        check("...and the surface recorded is the plural actually found",
              sorted(b["surface"] for b in res["backfill_candidates"]
                     if b["slug"] == "mentions"),
              ["confusion matrices", "hypotheses"])
        check("a mention only inside a TABLE ROW is not proposed",
              ("unlinkable", "confusion-matrix") in pairs, False)
        check("a mention only inside a FENCED BLOCK is not proposed",
              [b for b in res["backfill_candidates"] if b["slug"] == "unlinkable"], [])
        check("an entry that already links the target is not proposed",
              ("already", "confusion-matrix") in pairs, False)
        check("nothing in this vault is a collision candidate",
              res["collision_candidates"], [])
        # ...but a real plural pair sitting in the vault still fires probe (c),
        # which is the half CONVENTIONS.md 9 gives to this scanner alone.
        v = os.path.join(tmp, "v4b")
        _st_write(v, "roc-curve.md",
                  _st_entry("ROC curve", "**ROC curve** is a worked example.",
                            card="ROC curve"))
        _st_write(v, "roc-curves.md",
                  _st_entry("ROC curves", "**ROC curves** is a worked example.",
                            card="ROC curves"))
        res4b = scan(v)
        check("a plural pair already in the vault is a collision candidate",
              [(c["a"], c["b"], c["probe"]) for c in res4b["collision_candidates"]],
              [("roc-curve", "roc-curves", "plural")])

        # ------------------------------------------------------------------
        # 5. item 13 (stray key) and item 2 (unexpected key)
        # ------------------------------------------------------------------
        v = os.path.join(tmp, "v5")
        _st_write(v, "sw.md", _st_entry(
            "Sw", "**Sw** is a worked example.\n\n"
            "```yaml\ntype: Software\ntags:\n  - \"#computer-science\"\n```",
            type_="Software"))
        _st_write(v, "scarred.md", _st_entry(
            "Scarred", "**Scarred** is a worked example.\n\ntags:\n  - \"#statistics\""))
        _st_write(v, "obsidian.md", _st_entry(
            "Obsidian", "**Obsidian** is a worked example.",
            extra_keys="cssclasses: wide\npublish: true\n"))
        _st_write(v, "junk.md", _st_entry(
            "Junk", "**Junk** is a worked example.", extra_keys="mood: bright\n"))
        # item 12's literal-$ scan, item 2's bare-`parents:` scan, and item 4's
        # one-document-twice scan: each is a distinct reader over the same file.
        _st_write(v, "dollars.md", _st_entry(
            "Dollars", "**Dollars** is a worked example costing 5$ to run."))
        _st_write(v, "bare-parents.md", _st_entry(
            "Bare parents", "**Bare parents** is a worked example.")
            .replace("parents: []", "parents:"))
        _st_write(v, "block-parents.md", _st_entry(
            "Block parents", "**Block parents** is a worked example.",
            parents=('"[[junk]]"',)))
        _st_write(v, "twice-cited.md", _st_entry(
            "Twice cited", "**Twice cited** is a worked example.",
            sources=('"[[Doe_X_2025.pdf#page=2]]"',
                     '"[[Sources/Notes/doe_x_2025.md]]"')))
        res = scan(v)
        check("a literal $ in the body is item12",
              "item12" in _st_keys(res, "dollars"), True)
        check("a bare `parents:` is YAML null, not an empty list",
              "item2/parents-null" in _st_keys(res, "bare-parents"), True)
        check("...but a bare `parents:` WITH block items under it is not",
              "item2/parents-null" in _st_keys(res, "block-parents"), False)
        check("a .md source naming the same document as a .pdf source is item4 "
              "(stems folded for case and folder, as CONVENTIONS 7 requires of "
              "both copies of source_stem)",
              "Preserve both sources" in _st_msg(res, "twice-cited", "item4/source-identity"), True)
        check("a frontmatter key shown inside a FENCE is not a merge scar",
              "item13" in _st_keys(res, "sw"), False)
        check("a real stray frontmatter key in the body still is",
              "item13" in _st_keys(res, "scarred"), True)
        check("an Obsidian built-in key routes to item2/obsidian-key, not item2",
              (sorted(set(_st_keys(res, "obsidian"))), ), (["item2/obsidian-key"], ))
        check("...and says not to delete it",
              "DO NOT DELETE" in _st_msg(res, "obsidian", "item2/obsidian-key"), True)
        check("...for every such key",
              _st_msg(res, "obsidian", "item2/obsidian-key").count("Obsidian built-in"), 2)
        check("a genuinely off-schema key is still a plain item2",
              (sorted(set(_st_keys(res, "junk"))),
               "mood" in _st_msg(res, "junk", "item2")), (["item2"], True))

        # ------------------------------------------------------------------
        # 6. the hierarchy diagnostic
        # ------------------------------------------------------------------
        v = os.path.join(tmp, "v6")
        _st_write(v, "selfy.md", _st_entry(
            "Selfy", "**Selfy** is a worked example.", parents=('"[[selfy]]"',)))
        _st_write(v, "ping.md", _st_entry(
            "Ping", "**Ping** is a worked example.", parents=('"[[pong]]"',)))
        _st_write(v, "pong.md", _st_entry(
            "Pong", "**Pong** is a worked example.", parents=('"[[ping]]"',)))
        _st_write(v, "leaf.md", _st_entry(
            "Leaf", "**Leaf** is a worked example.", parents=('"[[root]]"',)))
        _st_write(v, "root.md", _st_entry("Root", "**Root** is a worked example."))
        for _a, _b in (("tri-a", "tri-b"), ("tri-b", "tri-c"), ("tri-c", "tri-a")):
            _st_write(v, _a + ".md", _st_entry(
                _a, "**%s** is a worked example." % _a, parents=('"[[%s]]"' % _b,)))
        res = scan(v)
        h = res["hierarchy_diagnostic"]
        check("a self-parent is reported", h["self_parented"], ["selfy"])
        check("a 2-CYCLE is reported", ["ping", "pong"] in h["parent_cycles"], True)
        check("a longer cycle is reported too, rotated to its first slug",
              ["tri-a", "tri-b", "tri-c"] in h["parent_cycles"], True)
        check("...each once, not once per member", len(h["parent_cycles"]), 2)
        check("an ordinary parent edge is not a cycle",
              any("leaf" in c or "root" in c for c in h["parent_cycles"]), False)
        check("check_rooting fires on the self-parent's discipline",
              [d["check_rooting"] for d in h["per_discipline"]], [True])

        # ------------------------------------------------------------------
        # 7. rename candidates -- `target_exists` is the ONLY thing standing
        #    between an approved rename and `mv wrong-name.md broken.md` over
        #    a file the user still has.  Every destination that a file already
        #    answers to must read True, whether or not that file PARSED.
        # ------------------------------------------------------------------
        v = os.path.join(tmp, "v7")
        _st_write(v, "broken.md", "no frontmatter at all, so this never parses\n")
        _st_write(v, "wrong-name.md", _st_entry(
            "Broken", "**Broken** is a worked example."))
        _st_write(v, "free-name.md", _st_entry(
            "Unoccupied", "**Unoccupied** is a worked example."))
        _st_write(v, "taken-name.md", _st_entry(
            "Occupied", "**Occupied** is a worked example."))
        _st_write(v, "occupied.md", _st_entry(
            "Occupied elsewhere", "**Occupied elsewhere** is a worked example."))
        res = scan(v)
        _tx = {r["slug"]: r["target_exists"] for r in res["rename_candidates"]}
        check("a rename onto a file that is ON DISK but did not parse is "
              "target_exists (the approved `mv` would destroy it)",
              _tx.get("wrong-name"), True)
        check("...and the unparsed file is still reported in its own right",
              ("broken", "item1") in _st_items(res), True)
        check("NEAR MISS: a rename onto a genuinely free destination stays "
              "target_exists: false",
              _tx.get("free-name"), False)
        check("a rename onto a destination held by a PARSED entry is still "
              "target_exists",
              _tx.get("taken-name"), True)

        # ------------------------------------------------------------------
        # 8. item 10 again -- the two ways a RESOLVING link was called
        #    dangling.  Both remedies write a file; both are destructive.
        # ------------------------------------------------------------------
        v = os.path.join(tmp, "v8")
        _st_write(v, "recall.md", _st_entry(
            "Recall", "**Recall** is a worked example.", aliases=('"tpr"',),
            card="Recall"))
        _st_write(v, "linker.md", _st_entry(
            "Linker", "**Linker** is a worked example that links [[tpr]] and "
                      "[[genuinely-absent]]."))
        _st_write(v, "listing.md", _st_entry(
            "Listing",
            "**Listing** is a worked example.\n\n"
            "```\nSee [[target-note]] for the syntax\n```\n\n"
            "It links [[sub-note]] once in prose, and shows the same link in "
            "`[[sub-note]]` form inline.",
            type_="Software"))
        _st_write(v, "sub-note.md", _st_entry(
            "Sub note", "**Sub note** is a worked example."))
        res = scan(v)
        check("a link to another entry's ALIAS is item10/alias, never a dangler",
              ("item10/alias" in _st_keys(res, "linker"),
               "tpr" in _st_msg(res, "linker", "item10/dangling")),
              (True, False))
        check("...and it names the owning entry and the piped rewrite",
              ('[[recall|tpr]]' in _st_msg(res, "linker", "item10/alias"),
               "never stub" in _st_msg(res, "linker", "item10/alias")),
              (True, True))
        check("NEAR MISS: a target that is neither entry nor alias is still "
              "item10/dangling",
              "genuinely-absent" in _st_msg(res, "linker", "item10/dangling"), True)
        check("a wikilink inside a FENCED block is not a dangling target "
              "(the remedy would create a file for a listing)",
              "target-note" in " ".join(p["message"] for p in res["problems"]), False)
        check("a wikilink inside an INLINE code span is not one either",
              _st_keys(res, "listing"), [])
        check("...so a target shown in a code span and linked once in prose is "
              "linked ONCE, not twice",
              "item10/dup" in _st_keys(res, "listing"), False)
        # An alias must not shadow item10/case: a FILE outranks an alias in
        # Obsidian, and the two findings have opposite fixes (rewrite the
        # target's spelling vs. pipe the link through the owner).
        v = os.path.join(tmp, "v8b")
        _st_write(v, "recall.md", _st_entry(
            "Recall", "**Recall** is a worked example.", aliases=('"tpr"',),
            card="Recall"))
        _st_write(v, "TPR.md", _st_entry("TPR", "**TPR** is a worked example."))
        _st_write(v, "caselink.md", _st_entry(
            "Caselink", "**Caselink** is a worked example linking [[tpr]]."))
        res = scan(v)
        check("NEAR MISS: a case-variant FILE outranks an alias of the same "
              "name — item10/case, not item10/alias",
              (_st_keys(res, "caselink"), "TPR" in _st_msg(res, "caselink", "item10/case")),
              (["item10/case"], True))

        # All THREE markdown spellings of a listing, and the look-alikes that
        # are not listings at all.  A check that knows only fenced blocks is a
        # rule about backticks, not about listings, and the entry written the
        # other way gets the finding whose remedy creates a file.
        v = os.path.join(tmp, "v8c")
        _listings = [
            # slug,     body after the opener,                          dangling?
            ("dbl",     "showing ``[[double-target]]`` inline.",         False),
            ("ind",     "\n\nLike this:\n\n    [[indented-target]]\n\nDone.", False),
            ("tabbed",  "\n\nLike this:\n\n\t[[tab-target]]\n\nDone.",   False),
            # ...and the three that are NOT code and must still be checked:
            # a list item's continuation content is indented for its own
            # reason, at one level and at two,
            ("lst",     "\n\n- a bullet\n\n    a continuation naming "
                        "[[list-target]].\n\nDone.",                     True),
            ("nested",  "\n\n- outer\n  - inner\n\n      a continuation "
                        "naming [[deep-target]].\n\nDone.",              True),
            # and an indented line with no blank line above it does not start
            # a code block at all -- it cannot interrupt a paragraph.
            ("interrupt", "\n    still the same paragraph, [[para-target]].", True),
        ]
        for _slug, _tail, _dangles in _listings:
            _st_write(v, _slug + ".md", _st_entry(
                _slug.title(), "**%s** is a worked example %s" % (_slug.title(), _tail),
                card=_slug.title()))
        # a 4-backtick fence WRAPPING a 3-backtick sample: CommonMark closes a
        # fence only on a >= run of the same character, so the whole thing is
        # one listing -- a blind toggle read the inner ``` as the close and the
        # [[link]] came back dangling (Software type, so item 6 stays quiet)
        _st_write(v, "quadfence.md", _st_entry(
            "Quadfence",
            "**Quadfence** is a worked example.\n\n"
            "````\n```\nSee [[quad-target]] for the syntax\n```\n````",
            type_="Software", card="Quadfence"))
        res = scan(v)
        check("a 4-backtick fence wrapping a 3-backtick sample is ONE listing, "
              "so its [[link]] is not a dangling target",
              _st_keys(res, "quadfence"), [])
        for _slug, _tail, _dangles in _listings:
            check("a wikilink in %s %s a dangling target"
                  % ({"dbl": "a DOUBLE-BACKTICK code span",
                      "ind": "a 4-SPACE INDENTED code block",
                      "tabbed": "a TAB-INDENTED code block",
                      "lst": "NEAR MISS: a list item's continuation",
                      "nested": "NEAR MISS: a nested list item's continuation",
                      "interrupt": "NEAR MISS: an indented line continuing a "
                                   "paragraph (no blank line above it)"}[_slug],
                     "is" if _dangles else "is NOT"),
                  "item10/dangling" in _st_keys(res, _slug), _dangles)
        check("...and none of the six produces any OTHER finding",
              sorted({k for _s, _t, _d in _listings for k in _st_keys(res, _s)}),
              ["item10/dangling"])

        # ------------------------------------------------------------------
        # 9. item 18 alias collisions, item 6 / item 12 fence spellings,
        #    the mandatory-key floor, and the date ordering compare
        # ------------------------------------------------------------------
        v = os.path.join(tmp, "v9")
        _st_write(v, "cased-a.md", _st_entry(
            "Cased a", "**Cased a** is a worked example.", aliases=('"lambda-rank"',)))
        _st_write(v, "cased-b.md", _st_entry(
            "Cased b", "**Cased b** is a worked example.", aliases=('"Lambda-Rank"',)))
        _st_write(v, "distinct.md", _st_entry(
            "Distinct", "**Distinct** is a worked example.", aliases=('"lambdarank"',)))
        res = scan(v)
        check("two aliases differing only in CASE are an item-18 collision "
              "(they are one name to Obsidian, and nobody else reports it)",
              ("item18" in _st_keys(res, "cased-b"),
               '"cased-a"' in _st_msg(res, "cased-b", "item18")), (True, True))
        check("...and the message keeps both raw spellings",
              ('"Lambda-Rank"' in _st_msg(res, "cased-b", "item18")
               and '"lambda-rank"' in _st_msg(res, "cased-b", "item18")), True)
        check("NEAR MISS: a genuinely different alias is not a collision",
              "item18" in _st_keys(res, "distinct"), False)

        v = os.path.join(tmp, "v10")
        _st_write(v, "tilde.md", _st_entry(
            "Tilde", "**Tilde** is a worked example.\n\n~~~\nmake install\n~~~"))
        _st_write(v, "backtick.md", _st_entry(
            "Backtick", "**Backtick** is a worked example.\n\n```\nmake install\n```"))
        _st_write(v, "tilde-sw.md", _st_entry(
            "Tilde sw", "**Tilde sw** is a worked example.\n\n~~~\necho $HOME\n~~~",
            type_="Software"))
        _st_write(v, "tilde-dollar.md", _st_entry(
            "Tilde dollar",
            "**Tilde dollar** is a worked example costing 5$ to run.\n\n"
            "~~~\necho $HOME $PATH\n~~~", type_="Software"))
        _st_write(v, "capzero.md", _st_entry(
            "Capzero", "**Capzero** is a worked example (`SomeClass` names it)."))
        _st_write(v, "capzero-sw.md", _st_entry(
            "Capzero sw", "**Capzero sw** is a worked example (`SomeClass` names it).",
            type_="Software"))
        _st_write(v, "extonly.md", _st_entry(
            "Extonly", "**Extonly** is a worked example saving `.csv` files."))
        res = scan(v)
        check("a ~~~ fence is a fenced code block for item 6, exactly as ``` is",
              (_st_keys(res, "tilde"), _st_keys(res, "backtick")),
              (["item6"], ["item6"]))
        check("a $ inside a ~~~ listing is not an unescaped literal $ "
              "(item 12's fix would write \\$ into the command)",
              _st_keys(res, "tilde-sw"), [])
        check("NEAR MISS: a literal $ in PROSE is still item12, and counted once",
              ("item12" in _st_keys(res, "tilde-dollar"),
               _st_msg(res, "tilde-dollar", "item12").startswith("1 unescaped")),
              (True, True))
        check("ONE backticked identifier in a non-Software entry is over the zero cap "
              "(the one-signpost allowance was retired 2026-08-16)",
              ("item6" in _st_keys(res, "capzero"),
               "cap is 0" in _st_msg(res, "capzero", "item6")), (True, True))
        check("...but the same identifier in a Software entry is legitimate",
              _st_keys(res, "capzero-sw"), [])
        check("NEAR MISS: a bare backticked file extension is not an identifier",
              _st_keys(res, "extonly"), [])

        v = os.path.join(tmp, "v11")
        _clean = _st_entry("Whole", "**Whole** is a worked example.")
        _st_write(v, "no-title.md", _clean.replace('title: "Whole"\n', ""))
        _st_write(v, "no-type.md", _clean.replace("type: Concept\n", ""))
        _st_write(v, "no-sources.md",
                  _clean.replace('sources:\n  - "[[Doe_X_2025.pdf#page=2]]"\n', ""))
        _st_write(v, "blank-title.md", _clean.replace('title: "Whole"', "title:"))
        _st_write(v, "unbolded.md", _st_entry(
            "Unbolded", "Unbolded is a worked example with no bold opener.",
            card="Unbolded"))
        _st_write(v, "whole.md", _clean)
        res = scan(v)
        check("a missing title: key is an item2 — without it item 5, item 16 "
              "and the rename candidate are all silent no-ops",
              ("item2" in _st_keys(res, "no-title"),
               "missing title" in _st_msg(res, "no-title", "item2")), (True, True))
        check("a title: key with NO VALUE is the same item2 (every gated check "
              "reads the value, not the key)",
              (_st_keys(res, "blank-title"),
               "carries no value" in _st_msg(res, "blank-title", "item2")),
              (["item2"], True))
        check("a full entry whose opener has NO bold span at all is item16",
              (_st_keys(res, "unbolded"),
               "no bold span" in _st_msg(res, "unbolded", "item16")),
              (["item16"], True))
        check("a missing type: key is an item2 too",
              "missing type: key" in _st_msg(res, "no-type", "item2"), True)
        check("...and a missing sources: key",
              "missing sources: key" in _st_msg(res, "no-sources", "item2"), True)
        check("NEAR MISS: an entry carrying all nine mandatory keys reports none",
              _st_keys(res, "whole"), [])

        # The item-3 date pair, in the four combinations that separate a
        # FORMAT finding from an ORDERING one.  The two must not be conflated
        # in either direction: a raw-string compare invents an ordering
        # violation on a correctly ordered entry (row 1) and misses a real one
        # (row 3), while regex-gating the ORDERING check on the format rule
        # (rather than only the format finding) silently drops rows 3 and 4 —
        # trading the false positive for a false negative.  `2026-2-05` names
        # one day and nothing else, so it is ordered; that it is also badly
        # spelled is a separate finding on a separate line.
        v = os.path.join(tmp, "v12")
        _dates = [
            # slug,       created,        updated,      ordering?, format?
            ("ok-unpad",  "2026-1-1",     "2026-01-02",  False, True),
            ("rev-pad",   "2026-12-01",   "2026-02-05",  True,  False),
            ("rev-unpad", "2026-12-01",   "2026-2-05",   True,  True),
            ("rev-both",  "2026-3-01",    "2026-1-02",   True,  True),
        ]
        for _slug, _c, _u, _ord, _fmt in _dates:
            _st_write(v, _slug + ".md",
                      _st_entry(_slug, "**%s** is a worked example." % _slug)
                      .replace("created: 2026-01-01", "created: " + _c)
                      .replace("updated: 2026-01-02", "updated: " + _u))
        res = scan(v)
        for _slug, _c, _u, _ord, _fmt in _dates:
            check("created %s / updated %s -> ordering finding: %s"
                  % (_c, _u, _ord),
                  "item3/user-action" in _st_keys(res, _slug), _ord)
            check("...and its FORMAT finding is independent of that: %s" % _fmt,
                  "not YYYY-MM-DD" in _st_msg(res, _slug, "item3"), _fmt)
        check("a well-formed, correctly ordered pair produces neither finding",
              [k for k in _st_keys(res, "ok-unpad") if k == "item3/user-action"], [])

        # ------------------------------------------------------------------
        # 10. --images: the Sources/Images/ embed check CONVENTIONS §1 makes
        #     this skill's, and which had no path to the folder at all.
        # ------------------------------------------------------------------
        v = os.path.join(tmp, "v13")
        _imgdir = os.path.join(tmp, "v13-images")
        os.makedirs(_imgdir)
        for _f in ("Doe_X_2025_fig_2.png", "doe_x_2025_fig_3.png"):
            open(os.path.join(_imgdir, _f), "w").close()
        _figbody = (
            "**Figured** is a worked example.\n\n"
            "![[Doe_X_2025_fig_99.png]]\n*A figure that is not on disk.*\n\n"
            "![[Doe_X_2025_fig_2.png]]\n*A figure that is.*\n\n"
            "![[Sources/Images/Doe_X_2025_fig_2.png]]\n*The same file, path-qualified.*\n\n"
            "![[Doe_X_2025_FIG_3.png]]\n*The same file in another case.*\n\n"
            "```\n![[Doe_X_2025_fig_98.png]]\n```")
        _st_write(v, "figured.md", _st_entry("Figured", _figbody))
        res_noimg = scan(v)
        res = scan(v, _imgdir)
        check("without --images nothing checks the embeds (the old behaviour, "
              "and the whole bug)",
              "item12/missing-image" in _st_keys(res_noimg, "figured"), False)
        check("an embed naming a file that is NOT in the image folder is "
              "item12/missing-image",
              ("item12/missing-image" in _st_keys(res, "figured"),
               "fig_99" in _st_msg(res, "figured", "item12/missing-image")),
              (True, True))
        check("...and it says not to delete the embed (the repair is at the "
              "filesystem, or is a §1a rename)",
              "DO NOT DELETE" in _st_msg(res, "figured", "item12/missing-image"), True)
        check("NEAR MISS: an embed that resolves — bare, path-qualified, or in "
              "another case on the vault's case-insensitive volume — is clean, "
              "and a fenced sample of embed syntax is not an embed",
              _st_msg(res, "figured", "item12/missing-image").count(
                  "not in the image folder"), 1)

        # ------------------------------------------------------------------
        # 11. item 19 -- the ## Flashcards heading is a LINE, not a substring
        # ------------------------------------------------------------------
        v = os.path.join(tmp, "v14")
        _st_write(v, "hhh.md",
                  _st_entry("Hhh", "**Hhh** is a worked example.")
                  .replace("## Flashcards", "### Flashcards"))
        _st_write(v, "midline.md", _st_entry(
            "Midline", "**Midline** is a worked example that mentions "
                       "## Flashcards mid-line."))
        res = scan(v)
        check("a ### Flashcards heading is a PRESENT section with a "
              "heading-spelling finding — never 'missing section', whose "
              "remedy adds a second section beside the rendered one",
              (_st_keys(res, "hhh"),
               "missing ## Flashcards" in _st_msg(res, "hhh", "item19"),
               'canonical heading is exactly "## Flashcards"'
               in _st_msg(res, "hhh", "item19")),
              (["item19"], False, True))
        check("a mid-line '## Flashcards' in prose neither starts the section "
              "nor splits the prose at a byte inside a sentence",
              _st_keys(res, "midline"), [])

        # ------------------------------------------------------------------
        # 12b. listings vs sections, fence exactness, and the leak needles —
        #      the 2026-08-24 review's fixes, each pinned by its reproduction.
        # ------------------------------------------------------------------
        v = os.path.join(tmp, "v12b")
        # (a) closing fence must be exactly `---`: `----` and `--- text` are
        #     not frontmatter to Obsidian (or to lint_entry) and must be item1
        #     here too, not a silently clean entry.
        _st_write(v, "four-dash.md",
                  _st_entry("Four dash", "**Four dash** is a worked example.",
                            card=False)
                  .replace("read: false\n---\n", "read: false\n----\n", 1))
        _st_write(v, "fence-text.md",
                  _st_entry("Fence text", "**Fence text** is a worked example.",
                            card=False)
                  .replace("read: false\n---\n", "read: false\n--- closed\n", 1))
        # (b) a fenced listing SHOWING section markers is not the section: the
        #     Related line and Flashcards heading inside the fence are samples,
        #     and the real prose past the fence is still scanned (the dangling
        #     link below must be found).
        _st_write(v, "sw-listing.md", _st_entry(
            "Sw listing",
            "**Sw listing** is a worked example.\n\n"
            "```\n**Related:** [[phantom-target|P]]\n## Flashcards\n"
            "sample def\n??\nSample term\n```\n\n"
            "After the fence it links [[genuinely-dangling]] in real prose.",
            type_="Software"))
        # (c) a stub whose only `## Flashcards` line sits in a fence has NO
        #     flashcards section.
        _st_write(v, "stub-fence.md", _st_entry(
            "Stub fence", "**Stub fence** is a placeholder.\n\n"
            "```\n## Flashcards\n```",
            sources=('"stub"',), card=False))
        # (d) tolerated heading spellings are a PRESENT section + a spelling
        #     finding, never "missing section".
        _st_write(v, "two-space.md",
                  _st_entry("Two space", "**Two space** is a worked example.")
                  .replace("## Flashcards", "##  Flashcards"))
        # (e) a stray `read:` line mid-body is an item13 scar like any other
        #     schema key (it is the schema's LAST key — the likeliest one-line scar).
        _st_write(v, "read-scar.md", _st_entry(
            "Read scar", "**Read scar** is a worked example.\n\nread: false"))
        # (f) leak needles: a hyphenated TITLE leaks in its natural spaced
        #     spelling; a disambiguated title's primary card (line 3 = base
        #     term) still gets the entry's alias needles.
        _st_write(v, "fine-tuning.md", _st_entry(
            "Fine-tuning", "**Fine-tuning** is a worked example.", card=False)
            + "\n---\n\n## Flashcards\n\nThe fine tuning of a pretrained model.\n??\nFine-tuning\n")
        _st_write(v, "feature-machine-learning.md", _st_entry(
            "Feature (machine learning)",
            "**Feature (machine learning)** is a worked example.",
            aliases=('"attribute"',), card=False)
            + "\n---\n\n## Flashcards\n\nAn input attribute a model consumes.\n??\nFeature\n")
        # (g) two alias spellings that fold to one name are reported within
        #     the entry, not only across entries.
        _st_write(v, "fold-dup.md", _st_entry(
            "Fold dup", "**Fold dup** is a worked example.",
            aliases=('"TPR"', '"tpr"')))
        res = scan(v)
        check("a `----` closing fence is item1, not a clean entry",
              _st_keys(res, "four-dash"), ["item1"])
        check("a `--- text` closing fence is item1, not a clean entry",
              _st_keys(res, "fence-text"), ["item1"])
        check("fenced Related/Flashcards samples produce no phantom section "
              "findings, and prose past the fence is still scanned",
              (_st_msg(res, "sw-listing", "item10/dangling""").count("does not resolve"),
               "phantom-target" in " ".join(p["message"] for p in res["problems"]),
               "genuinely-dangling" in _st_msg(res, "sw-listing", "item10/dangling")),
              (1, False, True))
        check("...and the real `## Flashcards` section (outside any fence) is "
              "still recognised on the same entry",
              "item19" in _st_keys(res, "sw-listing"), False)
        check("a stub whose only '## Flashcards' is inside a fence has no "
              "flashcards section",
              "item19" in _st_keys(res, "stub-fence"), False)
        check("'##  Flashcards' (double space) is a present section plus a "
              "heading-spelling finding, not a missing section",
              ("missing ## Flashcards" in _st_msg(res, "two-space", "item19"),
               'canonical heading is exactly "## Flashcards"'
               in _st_msg(res, "two-space", "item19")),
              (False, True))
        check("a stray `read:` line in the body is an item13 scar",
              "item13" in _st_keys(res, "read-scar"), True)
        check("a hyphenated title leaking in its SPACED spelling is caught",
              "fine tuning" in _st_msg(res, "fine-tuning", "item19").lower()
              and "leaks the answer" in _st_msg(res, "fine-tuning", "item19"),
              True)
        check("a disambiguated title's primary card (line 3 = base term) "
              "gets the alias needles — the alias leak is caught",
              'leaks the answer ("attribute")'
              in _st_msg(res, "feature-machine-learning", "item19"), True)
        check("two alias spellings folding to one name are an item18 finding "
              "within the entry",
              "differ only in case/normalization"
              in _st_msg(res, "fold-dup", "item18"), True)

        # (h) backfill: a candidate reached only through a single lowercase
        #     alias word is tagged bare_noun_alias; a title-surface candidate
        #     is not.
        v = os.path.join(tmp, "v12c")
        _st_write(v, "feature-machine-learning.md", _st_entry(
            "Feature (machine learning)",
            "**Feature (machine learning)** is a worked example.",
            aliases=('"attribute"',)))
        _st_write(v, "gradient-descent.md", _st_entry(
            "Gradient descent", "**Gradient descent** is a worked example."))
        _st_write(v, "user.md", _st_entry(
            "User", "**User** is a worked example. Each attribute feeds the "
                    "model, and gradient descent fits it."))
        res = scan(v)
        _bf = {(b["target"], b["bare_noun_alias"]) for b in res["backfill_candidates"]
               if b["slug"] == "user"}
        check("an alias-mediated bare-noun surface is tagged bare_noun_alias "
              "and a title surface is not",
              (("feature-machine-learning", True) in _bf,
               ("gradient-descent", False) in _bf),
              (True, True))

        v = os.path.join(tmp, "v13-validation")
        for i, source in enumerate(("[[Doe_X_2025.pdf]]", "[[Doe_X_2025.pdf#page=0]]",
                                  "[[Doe_X_2025.pdf#page=1garbage]]",
                                  "https://example.test/Doe_X_2025.pdf#page=1",
                                  "Doe_X_2025.pdf#page=1", "[[Note.md#Heading]]")):
            name = "Source %s" % i
            _st_write(v, slug(name) + ".md", _st_entry(
                name, "**%s** is a worked example." % name,
                sources=(json.dumps(source),)))
        for i, raw in enumerate(("banana", "[]", "[true, false]", '"banana"')):
            name = "Unknown %s" % i
            _st_write(v, slug(name) + ".md", _st_entry(
                name, "**%s** is a worked example." % name).replace("read: false", "read: " + raw))
        for i, raw in enumerate(("yes", "no", "0", "1")):
            name = "Known %s" % i
            _st_write(v, slug(name) + ".md", _st_entry(
                name, "**%s** is a worked example." % name).replace("read: false", "read: " + raw))
        _st_write(v, "no-source.md", _st_entry("No source", "**No source** is a worked example.", sources=()))
        _st_write(v, "self-case.md", _st_entry("Self case", "**Self case** is a worked example.",
                  parents=('"[[SELF-CASE]]"',)))
        for kind, target in (("md", "self-md.md"), ("path", "Wiki/self-path"),
                             ("block", "self-block^definition"), ("heading", "self-heading#Definition")):
            name = "Self " + kind
            _st_write(v, slug(name) + ".md", _st_entry(name, "**%s** is a worked example." % name,
                      parents=(json.dumps("[[%s]]" % target),)))
        _st_write(v, "cycle-left.md", _st_entry("Cycle left", "**Cycle left** is a worked example.",
                  parents=('"[[Wiki/CYCLE-RIGHT.md#Definition]]"',)))
        _st_write(v, "cycle-right.md", _st_entry("Cycle right", "**Cycle right** is a worked example.",
                  parents=('"[[cycle-left.md]]"',)))
        res = scan(v)
        check("every malformed source is an item4 finding",
              ["item4" in _st_keys(res, "source-%d" % i) for i in range(6)], [True] * 6)
        check("empty provenance is not a clean full entry", "item4" in _st_keys(res, "no-source"), True)
        check("unknown review states route report-only, never read-type",
              [sorted(k for k in _st_keys(res, "unknown-%d" % i) if k.startswith("item2/read"))
               for i in range(4)], [["item2/read-unknown"]] * 4)
        check("known review answers retain the spelling-only fix",
              ["item2/read-type" in _st_keys(res, "known-%d" % i) for i in range(4)], [True] * 4)
        check("resolving self-parent spellings are still self-parents",
              res["hierarchy_diagnostic"]["self_parented"],
              ["self-block", "self-case", "self-heading", "self-md", "self-path"])
        check("a cycle survives parent path, extension, case and anchor variants",
              res["hierarchy_diagnostic"]["parent_cycles"], [["cycle-left", "cycle-right"]])

        v = os.path.join(tmp, "v14-backfill")
        _st_write(v, "recall.md", _st_entry("Recall", "**Recall** measures sensitivity.",
                  aliases=('"true-positive-rate"',)))
        texts = {
            "inline": "**Inline** documents `Recall` as an identifier.",
            "indented": "**Indented** documents a listing.\n\n    Recall",
            "sample": "**Sample** displays `[[recall]]` literally.\n\nRecall measures sensitivity.",
            "anchor": "**Anchor** links [[recall#Definition|Recall]]. Recall measures sensitivity.",
            "qualified": "**Qualified** links [[sub/recall.md|Recall]]. Recall measures sensitivity.",
            "case": "**Case** links [[RECALL|Recall]]. Recall measures sensitivity.",
            "alias": "**Alias** links [[true-positive-rate|Sensitivity]]. Recall measures sensitivity.",
            "plain": "**Plain** explains why Recall measures sensitivity.",
        }
        for name, prose in texts.items():
            _st_write(v, name + ".md", _st_entry(name.title(), prose, type_="Software"))
        res = scan(v)
        check("backfill ignores listings and already-linked destinations, but a shown link cannot hide real prose",
              sorted(b["slug"] for b in res["backfill_candidates"] if b["target"] == "recall"),
              ["plain", "sample"])

        v = os.path.join(tmp, "v15-preserved-content")
        for name, tail in (
                ('studied', '<!--SR:!2026-09-20,30,250!2026-09-21,31,250-->\n\n<!-- preserved state -->\n'),
                ('multiline', '<!--SR:\n!2026-09-20,30,250\n\n!2026-09-21,31,250\n-->\n')):
            text = _st_entry(name.title(), '**%s** is a worked example.' % name.title())
            text = text.replace('read: false', 'read: true').replace('\n??\n', '\n!!\n') + tail
            _st_write(v, name + '.md', text)
        _st_write(v, 'extra.md', _st_entry('Extra', '**Extra** is a worked example.')
                  + '<!--SR:!2026-09-20,30,250-->\n\n<!-- preserved state -->\n\n'
                  + 'A different main claim.\n??\nAnother term\n')
        for name, fence in (('backticks', '```'), ('tildes', '~~~')):
            _st_write(v, name + '.md', _st_entry(
                name.title(), '**%s** is a worked example.\n\n' % name.title()
                + fence + 'text\n' + fence + 'not-a-close\n[[syntax-example]]\n'
                + fence, type_='Software'))
        _st_write(v, 'indented-closer.md', _st_entry('Indented closer',
                  '**Indented closer** displays syntax.\n\n```text\n    ```\n[[literal-syntax]]\n```',
                  type_='Software'))
        _st_write(v, 'nested-fence.md', _st_entry('Nested fence',
                  '**Nested fence** displays syntax.\n\n- An example:\n\n    ```text\n    [[literal-nested]]\n    ```',
                  type_='Software'))
        _st_write(v, 'sub/parsed.md', _st_entry('Parsed', '**Parsed** is a worked example.'))
        _st_write(v, 'sub/unparsed.md', 'A user note without frontmatter.\n')
        _st_write(v, 'linked.md', _st_entry('Linked', '**Linked** cites [[SUB/PARSED]], '
                  '[[sub/UNPARSED]], [[sub/parsed.MD]] and [[sub/unparsed.md]].'))
        before = {p: open(p, 'rb').read() for p in iter_entry_files(v)}
        res = scan(v)
        check("studied cards keep their multiline or separated review comments",
              [k for name in ('studied', 'multiline') for k in _st_keys(res, name)
               if k == 'item19'], [])
        check("metadata is not counted, but a genuine second card still is",
              '2 cards' in _st_msg(res, 'extra', 'item19'), True)
        check("a fence with trailing text cannot end the listing or hide the real flashcard",
              [k for name in ('backticks', 'tildes', 'indented-closer', 'nested-fence') for k in _st_keys(res, name)
               if k in ('item10/dangling', 'item19')], [])
        check("qualified case and explicit-extension links are never false danglers",
              'item10/dangling' in _st_keys(res, 'linked'), False)
        check("qualified unparsed destinations still route to the file's own repair",
              _st_keys(res, 'linked').count('item10/unparsed'), 2)
        check("the scanner leaves review histories and all input bytes untouched",
              all(open(p, 'rb').read() == content for p, content in before.items()), True)

        v = os.path.join(tmp, "v16-scalar-provenance")
        _st_write(v, 'commented.md', _st_entry('Commented', '**Commented** is a worked example.')
                  .replace('title: "Commented"', 'title: "Comm\\u0065nted" # user annotation')
                  .replace('read: false', 'read: true # already read')
                  .replace('sources:\n', 'sources: # origin\n# preserve this annotation\n'))
        for name, raw in (('null-title', 'null'), ('malformed', '"Malformed "yaml""')):
            _st_write(v, name + '.md', _st_entry(name.title(), '**Example** is a worked example.')
                      .replace('title: "' + name.title() + '"', 'title: ' + raw))
        _st_write(v, 'two-sources.md', _st_entry('Two sources', '**Two sources** is a worked example.',
                  sources=('"[[Study.pdf#page=2]]"', '"[[Study.md]]"')))
        res = scan(v)
        check("comments and decoded YAML title preserve a clean studied entry",
              _st_keys(res, 'commented'), [])
        check("null or malformed titles never produce rename candidates",
              [r for r in res['rename_candidates'] if r['slug'] in ('null-title', 'malformed')], [])
        check("malformed quoted YAML is a validity finding",
              'item1' in _st_keys(res, 'malformed'), True)
        check("same-stem PDF/clipping provenance is a report-only candidate",
              _st_keys(res, 'two-sources'), ['item4/source-identity'])
        for raw, want in (("[O'Reilly, real-alias]", ["O'Reilly", "real-alias"]),
                          ("['tail\\', 'real-alias']", ["tail\\", "real-alias"]),
                          ("['O''Reilly, Inc.', 'real-alias']", ["O'Reilly, Inc.", "real-alias"])):
            check("flow parsing retains every valid scalar in %s" % raw,
                  parse_fm('---\naliases: ' + raw + '\n---\n')['aliases'], want)
        from unittest.mock import patch
        def unreadable_walk(root, followlinks=False, onerror=None):
            if onerror:
                onerror(PermissionError(13, "permission denied", os.path.join(root, "private")))
            return iter(())
        with patch.object(os, "walk", unreadable_walk):
            inaccessible = scan(v)
        check("an unreadable directory is reported even with no readable entries",
              any(p['item'] == 'item0' and 'directory' in p['message']
                  for p in inaccessible['problems']), True)

        v = os.path.join(tmp, "v17-ambiguous-links")
        for name in ('first', 'second'):
            aliases = ('"shared-name"', '"single-name"') if name == 'first' else ('"shared-name"',)
            _st_write(v, name + '.md', _st_entry(name.title(), '**%s** is a worked example.' % name.title(),
                      aliases=aliases))
        for rel in ('a/Shared.md', 'b/shared.md'):
            _st_write(v, rel, _st_entry('Shared', '**Shared** is a worked example.'))
        _st_write(v, 'reader.md', _st_entry('Reader', '**Reader** cites '
                  '[[shared-name#Definition|the chosen term]], [[b/shared#Section]], '
                  'and [[single-name#Definition|the precise term]].'))
        res = scan(v)
        check("ambiguous file and alias owners never produce an automatic rewrite or dangler",
              _st_keys(res, 'reader').count('item10/ambiguous'), 2)
        check("an unambiguous alias rewrite keeps the existing anchor and display label",
              '[[first#Definition|the precise term]]' in _st_msg(res, 'reader', 'item10/alias'), True)
        check("ambiguous resolving links are not classified as dangling",
              'item10/dangling' in _st_keys(res, 'reader'), False)

        v = os.path.join(tmp, "v18-tally")
        _st_write(v, 'full.md', _st_entry('Full', '**Full** is a worked example.'))
        for name in ('stub-one', 'stub-two'):
            _st_write(v, name + '.md', _st_entry(name.title(), '**%s** is a placeholder.' % name.title(),
                      sources=('"stub"',), tags=(), card=False))
        res = scan(v)
        check("stub findings cannot inflate the reported percentage of affected full entries",
              [(p['entries'], p['pct_of_full']) for p in res['problem_tally'] if p['item'] == 'item8'],
              [(2, 0)])

        v = os.path.join(tmp, "v19-backfill-ownership")
        _st_write(v, 'aaa-technique.md', _st_entry('AAA technique',
                  '**AAA technique** is a worked example.', aliases=('"calibration"', '"shared-method"')))
        _st_write(v, 'calibration.md', _st_entry('Calibration',
                  '**Calibration** is a worked example.'))
        _st_write(v, 'second-technique.md', _st_entry('Second technique',
                  '**Second technique** is a worked example.', aliases=('"shared-method"', '"unique-method"')))
        for rel in ('first/duplicate.md', 'second/duplicate.md'):
            _st_write(v, rel, _st_entry('Duplicate', '**Duplicate** is a worked example.'))
        _st_write(v, 'reader.md', _st_entry('Reader',
                  '**Reader** uses calibration, shared methods, duplicates and a unique method.'))
        before = {p: Path(p).read_bytes() for p in iter_entry_files(v)}
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = main([v])
        res = json.loads(buf.getvalue())
        check("ambiguous backfill surfaces never choose a first owner, but unique aliases remain",
              (rc, [(b['slug'], b['target'], b['surface']) for b in res['backfill_candidates']]),
              (0, [('reader', 'second-technique', 'unique method')]))
        check("the ownership scan leaves every entry byte-for-byte unchanged",
              {p: Path(p).read_bytes() for p in iter_entry_files(v)}, before)

        v = os.path.join(tmp, "v20-bare-target-plurals")
        for name, title in (('entropy', 'Entropy'), ('information-entropy', 'Information entropy')):
            _st_write(v, name + '.md', _st_entry(title, '**%s** is a worked example.' % title))
        _st_write(v, 'reader.md', _st_entry('Reader',
                  '**Reader** compares entropies and information entropies.'))
        check("a plural cannot bypass the bare-common-noun destination gate",
              [(b['target'], b['surface']) for b in scan(v)['backfill_candidates']
               if b['slug'] == 'reader'], [('information-entropy', 'information entropies')])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    failed = [c for c in cases if not c[1]]
    for label, ok, got, want in cases:
        if not ok:
            print("FAIL  %s\n        got  %r\n        want %r" % (label, got, want))
    print("%d/%d self-test cases pass" % (len(cases) - len(failed), len(cases)))
    return 1 if failed else 0


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="scan_vault.py",
        description="Scan a wiki-builder vault and emit the wiki-linter Step 0 inventory as JSON.")
    ap.add_argument("wiki", nargs="?",
                    help="path to the vault's Wiki/ folder (walked recursively; "
                         "entries in subfolders are scanned too)")
    ap.add_argument("--images", metavar="DIR",
                    help="the vault's flat Sources/Images/ folder; with it, every "
                         "![[…]] image embed is checked to name a file that exists "
                         "(item12/missing-image). Omitted, that one check does not run")
    ap.add_argument("--out", metavar="FILE",
                    help="write the JSON to FILE instead of stdout")
    ap.add_argument("--indent", type=int, default=2, metavar="N",
                    help="JSON indent; 0 for one compact line (default: 2)")
    ap.add_argument("--test", action="store_true",
                    help="run the built-in self-test and exit")
    args = ap.parse_args(argv)
    if args.test:
        return run_self_test()
    if not args.wiki:
        print("missing required argument: the Wiki/ folder to scan (or --test)",
              file=sys.stderr)
        return 2
    if not os.path.isdir(args.wiki):
        ap.error("not a directory: %s" % args.wiki)
    # A mistyped --images must not read as "the folder is empty": that reports
    # EVERY embed in the vault as naming a missing file, and the model reading
    # that has no way to tell it from a genuinely broken vault. `isdir`, not
    # `exists` — a path that is a file satisfies `exists` and then lists nothing,
    # which is the same silent-empty failure. This script does not create the
    # folder, because a typo would create the typo.
    if args.images is not None and not os.path.isdir(args.images):
        ap.error("--images is not a directory: %s. No embed was checked; this is "
                 "not a vault with no images." % args.images)
    text = json.dumps(scan(args.wiki, args.images), ensure_ascii=False,
                      indent=(args.indent or None))
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(text + "\n")
        print("wrote %s" % args.out, file=sys.stderr)
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
