#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""vault_index.py -- walk a wiki folder and emit a JSON index of every entry.

Five separate places in wiki-builder's SKILL.md need a slug -> {title,
aliases, sources, tags, ...} index and none of them have one; the workflow
currently offers a bare ``ls '<wiki-folder>'``, which is a flat listing that
misses subfolders and carries no frontmatter at all.  This walks the folder
RECURSIVELY (``**/*.md``) and reads each entry's frontmatter and wikilinks.

Also the home of the hand-rolled frontmatter parser shared with
``lint_entry.py`` -- Python 3 standard library only, no pyyaml.  The parser
covers exactly the subset wiki-builder writes:

    key: "scalar"          scalar, quoted or bare (read: is a bare boolean)
    key:                   blank value (tags; a legacy bare parents:)
    key:                   block-form list
      - "item"
    key: ["a", "b"]        flow-form list

Anything it cannot parse becomes a recorded error rather than an exception:
a malformed entry is reported, never fatal.

PACKAGE CONVENTIONS (all four scripts in this folder): Python 3 standard
library only -- no pyyaml, no third-party anything.  Each file works as a
CLI *and* as an importable module, prints JSON to stdout, and takes
``--help``.  This module owns the hand-rolled frontmatter parser; the others
import it from here.  A malformed entry is always reported as a finding,
never a crash.

Module use:
    from vault_index import build_index, index_entry, parse_frontmatter
    idx = build_index("/path/to/Wiki")
    for e in idx["entries"]:
        print(e["slug"], e["title"], e["is_stub"])

CLI:
    vault_index.py <wiki-folder> [-o index.json] [--compact] [--source NAME ...]

Top-level index shape:
    {wiki_folder, generated, entry_count, stub_count, entries[],
     duplicate_slugs, problems[]}

``--source`` additionally emits ``source_matches[]``, matching only decoded
frontmatter provenance against literal source basenames. Nonempty problems
mean lookup data is incomplete or malformed, never an automatic skip decision.

Per-entry record:
    slug, path, relpath, title, type, aliases[], sources[], created, updated,
    description, tags[], parents[], is_stub,
    body_wikilink_targets[], related_wikilink_targets[], errors[]

``importance`` is NOT in the record: the field left the schema, and nothing
downstream read it (neither ``lint_entry.py``, which parses frontmatter
itself, nor ``find_collisions.py``, which consumes only slug/title/aliases).
Legacy entries still carrying the key are simply not reported on.

``is_stub`` is true only when ``sources:`` is exactly the literal string
``stub``.  Obsidian embeds (``![[fig.png]]``) are excluded from the wikilink
targets, and dot-directories are skipped during the walk.

Exit codes: 0 ok, 2 wiki folder missing / unreadable.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import re
import sys
import unicodedata as _ud

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

from yaml_scalars import parse_scalar, strip_comment  # noqa: E402


def fold_name(s):
    """Case- and Unicode-normalization-folded form of a slug or link target.

    Obsidian resolves wikilinks case-insensitively, and the documented vault
    lives on APFS, which is case- AND normalization-insensitive — so two slugs
    that differ only this way are one file there, and a link spelled either
    way opens it.  Any comparison answering "same file?" must go through this;
    exact string comparison is only right on the case-sensitive filesystems
    the plugin is tested on, which is why the mismatch never showed there.
    """
    return _ud.normalize("NFC", s or "").casefold()

__all__ = [
    "Field",
    "Frontmatter",
    "fold_name",
    "parse_frontmatter",
    "split_sections",
    "extract_wikilinks",
    "index_entry",
    "build_index",
    "source_matches",
    "iter_markdown_files",
    "unquote_scalar",
]

STUB_MARKER = "stub"

# `importance` is a LEGACY key: it was removed from the schema and is never
# written on a new entry, but the entries already in the vault carry it and
# nothing strips or flags it.  Keeping it here -- in its historical slot --
# is what makes lint_entry's field-order and unknown-key checks tolerate a
# legacy entry silently.  Do not remove it while such entries exist.
SCHEMA_ORDER = [
    "title", "type", "aliases", "sources", "created", "updated",
    "description", "tags", "importance", "parents", "read",
]

LIST_FIELDS = {"aliases", "sources", "tags", "parents"}

_KEY_RE = re.compile(r"^(?P<key>[A-Za-z_][A-Za-z0-9_-]*)\s*:(?P<rest>.*)$")
#: The same key shape, INDENTED -- i.e. nested under another key, which the
#: schema has no form for.  Reported by name rather than as an unparseable
#: line, and never adopted as a field of this entry.
_INDENTED_KEY_RE = re.compile(r"^\s+(?P<key>[A-Za-z_][A-Za-z0-9_-]*)\s*:")
_ITEM_RE = re.compile(r"^(?P<indent>\s*)-(?:\s+(?P<val>.*)|\s*)$")
# [[target]] / [[target|label]] -- the leading (?<!!) rejects ![[embeds]]
_WIKILINK_RE = re.compile(r"(?<!\!)\[\[([^\[\]]+?)\]\]")
_EMBED_RE = re.compile(r"\!\[\[([^\[\]]+?)\]\]")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_SOURCE_REF_RE = re.compile(r"\[\[[^\[\]|#]+\.(?:pdf#page=0*[1-9][0-9]*|md)\]\]", re.I)


# --------------------------------------------------------------------------
# minimal frontmatter parser
# --------------------------------------------------------------------------

class Field(object):
    """One frontmatter key, with enough raw detail for the quoting checks."""

    __slots__ = ("key", "kind", "raw_value", "values", "raw_items",
                 "line", "item_lines")

    def __init__(self, key, kind, raw_value, line):
        self.key = key
        self.kind = kind            # scalar | blank | block_list | flow_list
        self.raw_value = raw_value  # verbatim text after "key:" (may be "")
        self.values = []            # unquoted string values
        self.raw_items = []         # verbatim item text, quotes included
        self.line = line            # 1-indexed line number of the key
        self.item_lines = []

    @property
    def is_list(self):
        return self.kind in ("block_list", "flow_list")

    @property
    def scalar(self):
        """First value, or None when the field is blank."""
        return self.values[0] if self.values else None

    def to_dict(self):
        return {
            "key": self.key, "kind": self.kind, "raw_value": self.raw_value,
            "values": list(self.values), "raw_items": list(self.raw_items),
            "line": self.line,
        }


class Frontmatter(object):
    """Parsed frontmatter: ordered fields, the body text, and any errors."""

    __slots__ = ("fields", "order", "body", "body_start_line", "errors", "found")

    def __init__(self):
        self.fields = {}          # key -> Field
        self.order = []           # keys in file order (duplicates included)
        self.body = ""
        self.body_start_line = 1
        self.errors = []
        self.found = False

    def get(self, key):
        return self.fields.get(key)

    def values(self, key):
        f = self.fields.get(key)
        return list(f.values) if f else []

    def scalar(self, key):
        f = self.fields.get(key)
        return f.scalar if f else None


def unquote_scalar(raw):
    """Return a validated scalar and its quoting style, or raise ValueError."""
    return parse_scalar(raw)


def _split_flow(inner):
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


def parse_frontmatter(text):
    """Parse ``text`` into a :class:`Frontmatter`.  Never raises."""
    fm = Frontmatter()
    try:
        lines = text.split("\n")
    except Exception as exc:                                  # pragma: no cover
        fm.errors.append("could not split text: %s" % exc)
        return fm

    # The opening fence is EXACTLY `---` at line 1 (a trailing `\r` from CRLF
    # text is tolerated; leading whitespace is not).  ` ---` makes line 1 a
    # thematic break to Obsidian, which then shows no properties — scan_vault
    # (and its item1) has always been exact here, and the lenient `.strip()`
    # certified clean, in a single-file lint, an entry whose frontmatter
    # renders as literal text.  The closing fence is held to the same rule.
    if not lines or lines[0].rstrip("\r") != "---":
        fm.errors.append(
            "no YAML frontmatter: line 1 is not the opening '---' fence")
        fm.body = text
        fm.body_start_line = 1
        return fm

    close = None
    for i in range(1, len(lines)):
        if lines[i].rstrip("\r") == "---":
            close = i
            break
    if close is None:
        fm.errors.append("frontmatter is never closed by a '---' fence")
        fm.body = ""
        fm.body_start_line = len(lines) + 1
        return fm

    fm.found = True
    fm.body = "\n".join(lines[close + 1:])
    fm.body_start_line = close + 2

    current = None
    for offset in range(1, close):
        raw_line = lines[offset]
        lineno = offset + 1
        if raw_line.strip() == "" or raw_line.lstrip().startswith("#"):
            continue

        item_m = _ITEM_RE.match(raw_line)
        if item_m and current is not None and current.kind in ("blank", "block_list"):
            current.kind = "block_list"
            raw_item = (item_m.group("val") or "").strip()
            try:
                val, _style = unquote_scalar(raw_item)
            except ValueError as exc:
                fm.errors.append("line %d: unparseable YAML scalar: %s" % (lineno, exc))
                val = None
            current.raw_items.append(raw_item)
            current.values.append(val)
            current.item_lines.append(lineno)
            continue

        key_m = _KEY_RE.match(raw_line)
        if not key_m:
            # `_KEY_RE` is anchored at column 0, so an INDENTED key can never
            # match it -- it lands HERE.  The dedicated message used to sit
            # after the match, where nothing could ever reach it, and a nested
            # mapping was reported as an "unparseable line" instead: the same
            # severity, but it does not tell the reader what they wrote.  The
            # key is still deliberately NOT parsed into a field -- an indented
            # `source:` belongs to its parent mapping, and adopting it would
            # attribute another key's value to this entry.
            indented = _INDENTED_KEY_RE.match(raw_line)
            if indented:
                fm.errors.append("line %d: unexpected indented key %r "
                                 "(nested mappings are not part of the schema)"
                                 % (lineno, indented.group("key")))
            else:
                fm.errors.append("line %d: unparseable frontmatter line %r"
                                 % (lineno, raw_line))
            continue

        key = key_m.group("key")
        rest = key_m.group("rest")

        raw_value = strip_comment(rest).strip()
        if raw_value == "":
            field = Field(key, "blank", "", lineno)
        elif raw_value.startswith("[") and raw_value.endswith("]"):
            field = Field(key, "flow_list", raw_value, lineno)
            for raw_item in _split_flow(raw_value[1:-1]):
                try:
                    val, _style = unquote_scalar(raw_item)
                except ValueError as exc:
                    fm.errors.append("line %d: unparseable YAML scalar: %s" % (lineno, exc))
                    val = None
                field.raw_items.append(raw_item)
                field.values.append(val)
                field.item_lines.append(lineno)
        else:
            field = Field(key, "scalar", raw_value, lineno)
            try:
                val, _style = unquote_scalar(raw_value)
            except ValueError as exc:
                fm.errors.append("line %d: unparseable YAML scalar: %s" % (lineno, exc))
                val = None
            field.raw_items.append(raw_value)
            field.values.append(val)
            field.item_lines.append(lineno)

        if key in fm.fields:
            fm.errors.append("line %d: duplicate frontmatter key %r" % (lineno, key))
        fm.fields[key] = field
        fm.order.append(key)
        current = field

    return fm


# --------------------------------------------------------------------------
# body sectioning + wikilinks
# --------------------------------------------------------------------------

_FENCE_LINE_RE = re.compile(r"^\s*(`{3,}|~{3,})(.*)$")
#: A Flashcards heading as Obsidian renders one: ≤3 leading spaces, ``##`` or
#: ``###``, whitespace, the word.  Tolerant on purpose — every one of those
#: spellings SHOWS the reader a Flashcards section, so treating one as missing
#: prescribes adding a second section.  The canonical spelling is
#: ``## Flashcards`` exactly; lint_entry reports a tolerated variant as a
#: heading to fix.  scan_vault's ``_FLASH_HEAD_LINE`` is the same rule; the
#: two tools must agree on what counts as the section.
_FLASH_HEAD_LINE_RE = re.compile(r"^ {0,3}#{2,3}[ \t]+Flashcards[ \t]*$")


def split_sections(body):
    """Split an entry body into its three structural regions.

    Returns a dict with ``prose_lines``, ``related_line``, ``related_index``,
    ``flashcard_lines``, ``flashcards_index``, ``flashcards_head`` and
    ``separator_index`` (indexes relative to the body, 0-based; ``None`` when
    absent).

    Lines inside fenced code blocks are never section markers: a
    ``**Related:**`` or ``## Flashcards`` shown in a listing is a sample, and
    adopting it truncated the prose there and parsed the fence's contents as
    cards — phantom findings whose remediation edits the listing (scan_vault's
    ``regions`` applies the same rule).
    """
    lines = body.split("\n")
    related_index = None
    flashcards_index = None
    fence = None                          # the opening run, e.g. "````"
    for i, ln in enumerate(lines):
        m = _FENCE_LINE_RE.match(ln)
        if m and fence is None:
            fence = m.group(1)
            # Retain nested/list fences while rejecting a more-indented sample
            # as the closer of a top-level fence. Tabs count as four columns.
            fence_indent = max(3, len(ln[:m.start(1)].expandtabs(4)))
            continue
        if (m and m.group(1)[0] == fence[0]
                and len(m.group(1)) >= len(fence) and not m.group(2).strip()
                and len(ln[:m.start(1)].expandtabs(4)) <= fence_indent):
            fence = None
            continue
        if fence is not None:
            continue
        s = ln.strip()
        if related_index is None and s.startswith("**Related:**"):
            related_index = i
        if flashcards_index is None and _FLASH_HEAD_LINE_RE.match(ln.rstrip("\r")):
            flashcards_index = i

    separator_index = None
    if flashcards_index is not None:
        for i in range(flashcards_index - 1, -1, -1):
            s = lines[i].strip()
            if s == "":
                continue
            separator_index = i if s == "---" else None
            break

    candidates = [i for i in (related_index, separator_index, flashcards_index)
                  if i is not None]
    end = min(candidates) if candidates else len(lines)

    return {
        "lines": lines,
        "prose_lines": lines[:end],
        "related_line": lines[related_index] if related_index is not None else None,
        "related_index": related_index,
        "flashcards_index": flashcards_index,
        "flashcards_head": (lines[flashcards_index]
                            if flashcards_index is not None else None),
        "separator_index": separator_index,
        "flashcard_lines": (lines[flashcards_index + 1:]
                            if flashcards_index is not None else []),
    }


def _normalise_target(raw):
    """``"slug|Label"`` / ``"slug#anchor"`` / ``"slug^block"`` -> the target.

    ``^block`` anchors come off like ``#heading`` ones: Obsidian resolves
    ``[[x^quote]]`` to ``x.md``, so a target that keeps the caret is a slug
    no entry answers to -- the duplicate-link scan missed a second link to
    the same file, and the orphan audit read a resolving link as dangling.
    scan_vault has always stripped both (qc-items item 10).
    """
    target = raw.split("|", 1)[0]
    target = target.split("#", 1)[0]
    target = target.split("^", 1)[0]
    return target.strip()


def extract_wikilinks(text, include_embeds=False):
    """All ``[[target|label]]`` links in ``text`` as ``(target, label)`` pairs.

    Obsidian embeds (``![[fig.png]]``) are excluded unless asked for -- they
    are attachments, not entry references.
    """
    out = []
    pattern = _EMBED_RE if include_embeds else _WIKILINK_RE
    for m in pattern.finditer(text):
        raw = m.group(1)
        label = raw.split("|", 1)[1].strip() if "|" in raw else None
        out.append((_normalise_target(raw), label))
    return out


# --------------------------------------------------------------------------
# indexing
# --------------------------------------------------------------------------

def _is_stub(fm):
    """True when ``sources:`` is exactly the literal string ``stub``."""
    f = fm.get("sources")
    if f is None:
        return False
    vals = [v.strip() for v in f.values if v is not None]
    return len(vals) == 1 and vals[0] == STUB_MARKER


def index_entry(path, text=None, root=None):
    """Index one ``.md`` file.  Never raises -- problems land in ``errors``."""
    abspath = os.path.abspath(path)
    record = {
        "slug": os.path.splitext(os.path.basename(abspath))[0],
        "path": abspath,
        "relpath": (os.path.relpath(abspath, os.path.abspath(root))
                    if root else os.path.basename(abspath)),
        "title": None, "type": None, "aliases": [], "sources": [],
        "created": None, "updated": None, "description": None,
        "tags": [], "parents": [],
        "is_stub": False,
        "body_wikilink_targets": [], "related_wikilink_targets": [],
        "errors": [],
    }

    if text is None:
        try:
            # utf-8-sig, not utf-8: a leading BOM becomes part of the first line,
            # so `lines[0].strip() != "---"` and a perfectly valid entry was
            # reported as having "no YAML frontmatter".
            with open(abspath, "r", encoding="utf-8-sig") as fh:
                text = fh.read()
        except UnicodeDecodeError:
            try:
                with open(abspath, "r", encoding="utf-8-sig", errors="replace") as fh:
                    text = fh.read()
                record["errors"].append("file is not valid UTF-8; decoded with "
                                        "replacement characters")
            except Exception as exc:
                record["errors"].append("unreadable: %s: %s"
                                        % (type(exc).__name__, exc))
                return record
        except Exception as exc:
            record["errors"].append("unreadable: %s: %s" % (type(exc).__name__, exc))
            return record

    fm = parse_frontmatter(text)
    record["errors"].extend(fm.errors)

    record["title"] = fm.scalar("title")
    record["type"] = fm.scalar("type")
    record["created"] = fm.scalar("created")
    record["updated"] = fm.scalar("updated")
    record["description"] = fm.scalar("description")
    for key in ("aliases", "sources", "tags", "parents"):
        record[key] = [v for v in fm.values(key) if v not in (None, "")]
        field = fm.get(key)
        if field and field.kind == "scalar":
            record["errors"].append("%s: expected a list, not a scalar" % key)
        if field and any(v is None for v in field.values):
            record["errors"].append("%s: null or malformed list item" % key)
    for source in record["sources"]:
        if source != STUB_MARKER and not _SOURCE_REF_RE.fullmatch(source):
            record["errors"].append("sources: malformed local source reference %r" % source)
    record["is_stub"] = _is_stub(fm)

    sections = split_sections(fm.body)
    prose = "\n".join(sections["prose_lines"])
    record["body_wikilink_targets"] = [t for t, _l in extract_wikilinks(prose)]
    if sections["related_line"]:
        record["related_wikilink_targets"] = [
            t for t, _l in extract_wikilinks(sections["related_line"])]

    for key in ("created", "updated"):
        val = record[key]
        if val and not _DATE_RE.match(val):
            record["errors"].append("%s: %r is not YYYY-MM-DD" % (key, val))
    return record


def iter_markdown_files(root, on_error=None):
    """Yield every ``.md`` path under ``root``, recursively, sorted.

    Dot-directories and ``.obsidian`` are skipped so vault plumbing never
    lands in the index.  Symlinked subfolders are followed, for the reason
    scan_vault's walk gives: a synced or shared subfolder under the wiki is
    a symlink in plenty of real vaults, and skipping it hides its entries
    from the collision probes -- verdict ``create``, duplicate written.
    ``seen`` keeps a symlink loop from walking forever.
    """
    root = os.path.abspath(root)
    found = []
    seen = set()
    for dirpath, dirnames, filenames in os.walk(root, followlinks=True, onerror=on_error):
        try:
            st = os.stat(dirpath)
            key = (st.st_ino, st.st_dev)
        except OSError:
            key = dirpath
        if key in seen:
            dirnames[:] = []
            continue
        seen.add(key)
        dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))
        for name in filenames:
            if name.lower().endswith(".md") and not name.startswith("."):
                found.append(os.path.join(dirpath, name))
    return sorted(found)


def build_index(root):
    """Build the full index dict for the wiki folder at ``root``."""
    root = os.path.abspath(root)
    index = {
        "wiki_folder": root,
        "generated": _dt.datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "entry_count": 0,
        "stub_count": 0,
        "entries": [],
        "duplicate_slugs": {},
        "problems": [],
    }
    if not os.path.isdir(root):
        index["problems"].append("wiki folder does not exist: %s" % root)
        return index

    by_slug = {}          # folded slug -> [(display slug, relpath)]
    def walk_error(exc):
        index["problems"].append("unreadable wiki directory: %s" % exc)

    for path in iter_markdown_files(root, on_error=walk_error):
        rec = index_entry(path, root=root)
        index["entries"].append(rec)
        by_slug.setdefault(fold_name(rec["slug"]), []).append(
            (rec["slug"], rec["relpath"]))
        for err in rec["errors"]:
            index["problems"].append("%s: %s" % (rec["relpath"], err))

    index["entries"].sort(key=lambda r: r["slug"])
    index["entry_count"] = len(index["entries"])
    index["stub_count"] = sum(1 for r in index["entries"] if r["is_stub"])
    # Grouped on the FOLDED slug: two stems differing only in case or Unicode
    # normalization are one name to Obsidian and to the vault's own APFS
    # volume, so they collide exactly like two identical stems in subfolders.
    index["duplicate_slugs"] = {
        pairs[0][0]: [p for _s, p in pairs]
        for _f, pairs in by_slug.items() if len(pairs) > 1}
    for slug, paths in sorted(index["duplicate_slugs"].items()):
        index["problems"].append(
            "slug %r occurs in %d files (Obsidian resolves links to it case-"
            "insensitively, so subfolder and case/normalization variants all "
            "collide): %s" % (slug, len(paths), ", ".join(paths)))
    return index


def source_matches(index, filenames):
    """Entries citing the supplied literal PDF/Markdown basenames.

    Read only decoded frontmatter sources, never example links in body prose.
    Folder qualifications, anchors, case and Unicode normalization do not
    change the basename. Disambiguators such as _2 remain part of its name.
    The caller must inspect index problems before treating a match as grounds
    for an automatic already-processed skip.
    """
    requested = {fold_name(str(name).replace("\\", "/").rsplit("/", 1)[-1])
                 for name in filenames}
    matches = []
    for entry in index["entries"]:
        cited = []
        for source in entry["sources"]:
            if not isinstance(source, str) or not _SOURCE_REF_RE.fullmatch(source):
                continue
            target = source[2:-2].split("|", 1)[0].split("#", 1)[0].strip()
            basename = target.replace("\\", "/").rsplit("/", 1)[-1]
            if fold_name(basename) in requested:
                cited.append(source)
        if cited:
            matches.append({"slug": entry["slug"], "path": entry["path"],
                            "relpath": entry["relpath"], "sources": cited})
    return matches


# --------------------------------------------------------------------------
# self-test
# --------------------------------------------------------------------------
#
# This module is the load-bearing one: `find_collisions.py` decides whether a
# file may be written from the index it returns, and `lint_entry.py` imports
# its parser wholesale.  A field this walk silently drops is a probe that
# never fires -- an `aliases:` list read as a string means the alias is
# unprobed, and step 4 writes a second entry for something the vault already
# has.  So the cases below pin the SHAPE the two consumers read, not just the
# happy path.
#
#     python3 vault_index.py --test

def _st_entry_text(title, aliases_flow=False, stub=False, extra="", body=None):
    lines = ["---", 'title: "%s"' % title, "type: Concept"]
    if aliases_flow:
        lines.append('aliases: ["%s-alias", "%s-second"]'
                     % (title.lower(), title.lower()))
    else:
        lines.append("aliases:")
        lines.append('  - "%s-alias"' % title.lower())
        lines.append('  - "%s-second"' % title.lower())
    lines.append('sources: ["stub"]' if stub else "sources:")
    if not stub:
        lines.append('  - "[[Doe_X_2025.pdf#page=2]]"')
    lines += ["created: 2026-01-01", "updated: 2026-01-02",
              'description: "A worked example used by the self-test."',
              "tags:", '  - "#statistics"']
    if extra:
        lines.append(extra)
    lines += ["parents: []", "read: false", "---"]
    if body is None:
        body = ("**%s** links [[other]] and [[third|a label]] and embeds "
                "![[figure.png]].\n\n**Related:** [[other|Other]]\n\n---\n\n"
                "## Flashcards\n\nA definition.\n??\n%s\n" % (title, title))
    return "\n".join(lines) + "\n" + body


def run_self_test():
    import io
    import contextlib
    import shutil
    import tempfile
    cases = []

    def check(label, got, want):
        cases.append((label, got == want, got, want))

    tmp = tempfile.mkdtemp(prefix="vault_index-selftest-")
    try:
        wiki = os.path.join(tmp, "Wiki")
        os.makedirs(os.path.join(wiki, "sub", "deeper"))
        os.makedirs(os.path.join(wiki, ".obsidian"))

        def put(rel, text, encoding="utf-8"):
            path = os.path.join(wiki, *rel.split("/"))
            mode, kw = (("wb", {}) if isinstance(text, bytes)
                        else ("w", {"encoding": encoding}))
            with open(path, mode, **kw) as fh:
                fh.write(text)

        put("anchor.md", _st_entry_text("Anchor"))
        put("beta.md", _st_entry_text("Beta", aliases_flow=True))
        put("stubby.md", _st_entry_text("Stubby", stub=True))
        put("sub/nested.md", _st_entry_text("Nested"))
        put("sub/deeper/deep.md", _st_entry_text("Deep"))
        put(".obsidian/workspace.md", _st_entry_text("Plumbing"))
        put(".hidden.md", _st_entry_text("Hidden"))
        put("no-fm.md", "just prose, no fence\n")
        put("bom.md", "﻿" + _st_entry_text("Bom"))
        put("binary.md", b'---\ntitle: "Caf\xe9"\n---\nbody\n')
        put("sub/Anchor.md", _st_entry_text("Anchor"))     # case-variant duplicate

        # a symlinked subfolder: real vaults hold synced folders this way, and
        # an entry the walk cannot see is one the collision probes never probe
        linked = os.path.join(tmp, "linked-target")
        os.makedirs(linked)
        with open(os.path.join(linked, "symlinked.md"), "w",
                  encoding="utf-8") as fh:
            fh.write(_st_entry_text("Symlinked"))
        have_symlink = True
        try:
            os.symlink(linked, os.path.join(wiki, "linkdir"))
        except (OSError, NotImplementedError, AttributeError):
            have_symlink = False

        idx = build_index(wiki)
        slugs = [r["slug"] for r in idx["entries"]]

        # -- the walk --------------------------------------------------------
        check("the walk is RECURSIVE",
              [s for s in ("nested", "deep") if s in slugs], ["nested", "deep"])
        if have_symlink:
            check("an entry in a SYMLINKED subfolder is indexed",
                  "symlinked" in slugs, True)
        check("dot-directories and dotfiles are skipped",
              [s for s in slugs if s in ("workspace", ".hidden")], [])
        check("entries are sorted by slug", slugs, sorted(slugs))
        check("entry_count counts what is in entries",
              idx["entry_count"], len(idx["entries"]))
        check("stub_count counts only stubs", idx["stub_count"], 1)

        # -- the shape the other two scripts consume ------------------------
        check("the top-level index keys are the documented ones",
              sorted(idx),
              sorted(["wiki_folder", "generated", "entry_count", "stub_count",
                      "entries", "duplicate_slugs", "problems"]))
        anchor = [r for r in idx["entries"] if r["slug"] == "anchor"][0]
        check("the per-entry record keys are the documented ones",
              sorted(anchor),
              sorted(["slug", "path", "relpath", "title", "type", "aliases",
                      "sources", "created", "updated", "description", "tags",
                      "parents", "is_stub", "body_wikilink_targets",
                      "related_wikilink_targets", "errors"]))
        check("`importance` is deliberately absent from the record",
              "importance" in anchor, False)
        check("relpath is relative to the wiki root",
              [r["relpath"] for r in idx["entries"] if r["slug"] == "nested"],
              [os.path.join("sub", "nested.md")])

        # -- frontmatter reading --------------------------------------------
        check("a block-form aliases: list is a LIST of strings",
              anchor["aliases"], ["anchor-alias", "anchor-second"])
        beta = [r for r in idx["entries"] if r["slug"] == "beta"][0]
        check("a FLOW-form aliases: list parses identically",
              beta["aliases"], ["beta-alias", "beta-second"])
        decoded = parse_frontmatter(
            '---\ntitle: "Garc\\u00eda" # annotation\n'
            'aliases: ["garc\\u00eda", "other"] # annotation\n'
            'sources: # origin follows the comment\n# preserved annotation\n'
            '  - "[[Study.pdf#page=2]]" # physical page\n---\n')
        check("comments and YAML escapes retain decoded title, aliases and sources",
              (decoded.scalar("title"), decoded.values("aliases"),
               decoded.values("sources"), decoded.errors),
              ("García", ["garcía", "other"], ["[[Study.pdf#page=2]]"], []))
        for raw, want in (("[O'Reilly, real-alias]", ["O'Reilly", "real-alias"]),
                          ("['tail\\', 'real-alias']", ["tail\\", "real-alias"]),
                          ("['O''Reilly, Inc.', 'real-alias']", ["O'Reilly, Inc.", "real-alias"])):
            parsed = parse_frontmatter('---\naliases: ' + raw + '\n---\n')
            check("flow parsing retains every alias in %s" % raw,
                  (parsed.values("aliases"), parsed.errors), (want, []))
        for raw in ('"Malformed "yaml""', '"bad\\q"', '"unterminated'):
            parsed = parse_frontmatter('---\ntitle: ' + raw + '\n---\n')
            check("malformed scalar is recorded, not used as a title: %s" % raw,
                  (parsed.scalar("title"), bool(parsed.errors)), (None, True))
        check("bare YAML null is not an entity title",
              parse_frontmatter('---\ntitle: null\n---\n').scalar("title"), None)
        check("scalars are unquoted",
              (anchor["title"], anchor["type"], anchor["created"]),
              ("Anchor", "Concept", "2026-01-01"))
        check("sources: is a list even in block form",
              anchor["sources"], ["[[Doe_X_2025.pdf#page=2]]"])
        check("parents: [] is an empty list, not a string", anchor["parents"], [])
        check("a BOM does not hide the frontmatter",
              [r["title"] for r in idx["entries"] if r["slug"] == "bom"], ["Bom"])
        check("a file that is not UTF-8 is reported, not fatal",
              any("not valid UTF-8" in e
                  for r in idx["entries"] if r["slug"] == "binary"
                  for e in r["errors"]), True)
        check("a file with no frontmatter is an error on the record, not a crash",
              any("no YAML frontmatter" in e
                  for r in idx["entries"] if r["slug"] == "no-fm"
                  for e in r["errors"]), True)

        # -- stub detection ---------------------------------------------------
        check("is_stub is true only for sources: [\"stub\"]",
              sorted(r["slug"] for r in idx["entries"] if r["is_stub"]), ["stubby"])
        check("a flow-form stub marker is recognised",
              _is_stub(parse_frontmatter('---\nsources: ["stub"]\n---\n')), True)
        check("...and a block-form one",
              _is_stub(parse_frontmatter('---\nsources:\n  - "stub"\n---\n')), True)
        check("a stub marker beside a real source is NOT a stub",
              _is_stub(parse_frontmatter(
                  '---\nsources:\n  - "stub"\n  - "[[X.pdf#page=1]]"\n---\n')), False)

        # -- wikilinks --------------------------------------------------------
        check("body wikilinks are extracted, embeds excluded",
              anchor["body_wikilink_targets"], ["other", "third"])
        check("the Related footer is extracted separately",
              anchor["related_wikilink_targets"], ["other"])
        check("extract_wikilinks strips a display pipe and BOTH anchor forms",
              extract_wikilinks("[[a|Label]] [[b#heading]] [[c^block]] ![[d.png]]"),
              [("a", "Label"), ("b", None), ("c", None)])
        check("...and can be asked for embeds instead",
              extract_wikilinks("[[a]] ![[d.png]]", include_embeds=True),
              [("d.png", None)])

        # -- duplicate slugs, folded -----------------------------------------
        check("two files whose stems differ only in CASE are one name",
              sorted(idx["duplicate_slugs"]), ["anchor"])
        check("...and both paths are reported",
              sorted(os.path.basename(p) for p in idx["duplicate_slugs"]["anchor"]),
              ["Anchor.md", "anchor.md"])
        check("fold_name folds case and Unicode normalization",
              (fold_name("ROC-Curve") == fold_name("roc-curve"),
               fold_name("é") == fold_name("é")), (True, True))

        # -- parser edge cases ------------------------------------------------
        fm = parse_frontmatter('---\ntitle: "A"\ntitle: "B"\n---\nbody\n')
        check("a duplicate frontmatter key is an error",
              any("duplicate" in e for e in fm.errors), True)
        fm = parse_frontmatter('---\ntitle: "A"\n  nested: x\n---\nbody\n')
        check("an indented key is an error (no nested mappings in the schema)",
              any("indented key" in e for e in fm.errors), True)
        fm = parse_frontmatter('---\ntitle: "A"\nnever closed\n')
        check("an unterminated fence is an error and yields no fields",
              (fm.found, any("never closed" in e for e in fm.errors)), (False, True))
        fm = parse_frontmatter("no fence at all\n")
        check("a file with no fence keeps its whole text as the body",
              (fm.found, fm.body), (False, "no fence at all\n"))
        check("unquote_scalar reports the style it found",
              [unquote_scalar(r) for r in ('"a"', "'a'", "a", "", None)],
              [("a", "double"), ("a", "single"), ("a", "bare"), ("", "empty"),
               (None, "empty")])
        fm = parse_frontmatter('---\ntitle: "A"\nparents:\n---\nbody\n')
        check("a bare key is `blank`, not a scalar",
              (fm.get("parents").kind, fm.values("parents")), ("blank", []))

        # -- sections ---------------------------------------------------------
        sec = split_sections("Prose one.\n\n**Related:** [[a|A]]\n\n---\n\n"
                             "## Flashcards\n\nDef.\n??\nTerm\n")
        check("split_sections separates prose / related / flashcards",
              ("\n".join(sec["prose_lines"]).strip(),
               sec["related_line"].strip(),
               [l for l in sec["flashcard_lines"] if l.strip()]),
              ("Prose one.", "**Related:** [[a|A]]", ["Def.", "??", "Term"]))
        check("...and finds the --- separator above the heading",
              sec["separator_index"] is not None, True)
        check("...and exposes the heading line as spelled",
              sec["flashcards_head"], "## Flashcards")
        for fence in ('```', '~~~'):
            sec = split_sections('Prose.\n\n' + fence + 'text\n' + fence + 'not-a-close\n'
                                 '## Flashcards\n' + fence + '\n\nMore prose.\n\n---\n\n'
                                 '## Flashcards\n\nDef.\n??\nTerm\n')
            check("a fence with trailing text does not expose a sample heading: %s" % fence,
                  ('More prose.' in '\n'.join(sec['prose_lines']),
                   [l for l in sec['flashcard_lines'] if l.strip()]),
                  (True, ['Def.', '??', 'Term']))
        # Fenced samples are SHOWN, not asserted: markers inside a listing do
        # not start a section, and the real ones after the fence still do.
        sec = split_sections("Prose.\n\n```\n**Related:** [[x|X]]\n"
                             "## Flashcards\n```\n\nMore prose.\n\n"
                             "**Related:** [[a|A]]\n\n---\n\n"
                             "## Flashcards\n\nDef.\n??\nTerm\n")
        check("markers inside a fenced listing do not start a section; the "
              "real ones after the fence do",
              (sec["related_line"].strip(), "More prose." in
               "\n".join(sec["prose_lines"]),
               [l for l in sec["flashcard_lines"] if l.strip()]),
              ("**Related:** [[a|A]]", True, ["Def.", "??", "Term"]))
        sec = split_sections("Prose.\n\n---\n\n### Flashcards\n\nDef.\n??\nTerm\n")
        check("a tolerated heading spelling still marks the section, and is "
              "exposed for the spelling check",
              (sec["flashcards_index"] is not None, sec["flashcards_head"]),
              (True, "### Flashcards"))

        # -- fence exactness --------------------------------------------------
        fm = parse_frontmatter(' ---\ntitle: "A"\n---\nbody\n')
        check("a leading space before the opening fence is NOT frontmatter "
              "(Obsidian reads a thematic break there)",
              (fm.found, any("no YAML frontmatter" in e for e in fm.errors)),
              (False, True))
        fm = parse_frontmatter('---\ntitle: "A"\n --- \nbody\n')
        check("a whitespace-padded line does not close the fence",
              (fm.found, any("never closed" in e for e in fm.errors)),
              (False, True))
        fm = parse_frontmatter('---\r\ntitle: "A"\r\n---\r\nbody\r\n')
        check("CRLF text still parses (trailing \\r tolerated on the fences)",
              (fm.found, fm.scalar("title")), (True, "A"))
        check("a degenerate flow list `[,]` holds no phantom empty items",
              _split_flow(","), [])

        # -- a bad date is reported on the record ------------------------------
        rec = index_entry(os.path.join(wiki, "anchor.md"),
                          text=_st_entry_text("Anchor").replace("2026-01-01", "2026-1-1"))
        check("a malformed date is a recorded error, not an exception",
              any("YYYY-MM-DD" in e for e in rec["errors"]), True)

        # -- a missing folder is a problem, not a traceback ---------------------
        missing = build_index(os.path.join(tmp, "nope"))
        check("a missing wiki folder is reported and returns an empty index",
              (missing["entry_count"], bool(missing["problems"])), (0, True))

        # The source query uses provenance, never a prose example, and names
        # are compared literally (including numeric disambiguators).
        put("cited.md", _st_entry_text("Cited").replace(
            '"[[Doe_X_2025.pdf#page=2]]"',
            '"[[Sources/PDFs/Garc\\u00eda_Study_2025.pdf#page=02]]" # origin'))
        put("mentioned.md", _st_entry_text("Mentioned", body='An example uses [[García_Study_2025.pdf]].\n'))
        put("different.md", _st_entry_text("Different").replace(
            'Doe_X_2025.pdf', 'García_Study_2025_2.pdf'))
        put("bad-source.md", _st_entry_text("Bad source").replace(
            'Doe_X_2025.pdf#page=2', 'García_Study_2025.pdf#page=0'))
        source_idx = build_index(wiki)
        check("source matching folds Unicode/case but ignores body-only and _2 citations",
              [r["slug"] for r in source_matches(source_idx, ["GARCI\u0301A_STUDY_2025.PDF"])],
              ["cited"])
        check("malformed provenance remains a problem rather than an automatic source match",
              any("bad-source.md: sources:" in p for p in source_idx["problems"]), True)
        out_path = os.path.join(tmp, "source-index.json")
        with contextlib.redirect_stdout(io.StringIO()):
            rc = main([wiki, "--source", "García_Study_2025.pdf", "--source", "DifferentNote.md", "-o", out_path])
        with open(out_path, encoding="utf-8") as fh:
            cli_idx = json.load(fh)
        check("repeatable CLI --source adds the same provenance matches",
              (rc, [r["slug"] for r in cli_idx["source_matches"]]), (0, ["cited"]))

        from unittest.mock import patch
        def unreadable_walk(root, followlinks=False, onerror=None):
            if onerror:
                onerror(PermissionError(13, "permission denied", os.path.join(root, "private")))
            return iter(())
        with patch.object(os, "walk", unreadable_walk):
            inaccessible = build_index(wiki)
        check("an unreadable directory cannot masquerade as a clean empty index",
              (inaccessible["entry_count"], any("unreadable wiki directory" in p for p in inaccessible["problems"])),
              (0, True))

        unicode_wiki = os.path.join(tmp, "unicode-space")
        os.makedirs(unicode_wiki)
        unicode_titles = {"plan-2": "Plan\u00a0#2", "path-value": "path:\u00a0value"}
        for name, title in unicode_titles.items():
            text = _st_entry_text("Unicode").replace('title: "Unicode"', 'title: ' + title)
            with open(os.path.join(unicode_wiki, name + '.md'), 'w', encoding='utf-8') as fh:
                fh.write(text)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = main([unicode_wiki])
        unicode_idx = json.loads(buf.getvalue())
        check("public index preserves Unicode spaces that are YAML scalar content",
              (rc, {r['slug']: r['title'] for r in unicode_idx['entries']}, unicode_idx['problems']),
              (0, unicode_titles, []))

        # -- the CLI still refuses a real run with no folder --------------------
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            rc = main([])
        check("a run with no wiki folder exits 2 and says so",
              (rc, "wiki_folder" in buf.getvalue()), (2, True))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    failed = [c for c in cases if not c[1]]
    for label, ok, got, want in cases:
        if not ok:
            print("FAIL  %s\n        got  %r\n        want %r" % (label, got, want))
    print("%d/%d self-test cases pass" % (len(cases) - len(failed), len(cases)))
    return 1 if failed else 0


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def _build_parser():
    p = argparse.ArgumentParser(
        prog="vault_index.py",
        description="Recursively index an Obsidian wiki folder to JSON "
                    "(stdlib only).",
        epilog="example: vault_index.py ~/Vault/Wiki -o /tmp/index.json",
    )
    # `nargs="?"`, so `--test` is reachable: argparse refuses a missing
    # positional before main() runs, and the self-test needs no folder.  A real
    # run without one is refused below, by name and with exit 2.
    p.add_argument("wiki_folder", nargs="?",
                   help="folder containing the wiki entries")
    p.add_argument("--test", action="store_true",
                   help="run the built-in self-test and exit")
    p.add_argument("-o", "--output", help="write JSON here instead of stdout "
                                          "(a one-line status still goes to stdout)")
    p.add_argument("--compact", action="store_true",
                   help="emit compact JSON instead of indented")
    p.add_argument("--source", action="append", default=[], metavar="FILENAME",
                   help="also report source_matches for this literal source basename "
                        "from decoded frontmatter only (repeat for a paired PDF/note)")
    return p


def main(argv=None):
    args = _build_parser().parse_args(argv)
    if args.test:
        return run_self_test()
    if not args.wiki_folder:
        print(json.dumps({"ok": False,
                          "error": "missing required argument: wiki_folder "
                                   "(the folder holding the wiki entries), or --test"},
                         indent=2))
        return 2
    index = build_index(args.wiki_folder)
    if not os.path.isdir(args.wiki_folder):
        print(json.dumps(index, indent=2, ensure_ascii=False))
        return 2
    if args.source:
        index["source_matches"] = source_matches(index, args.source)

    dumped = json.dumps(index, ensure_ascii=False,
                        **({} if args.compact else {"indent": 2}))
    if args.output:
        try:
            with open(args.output, "w", encoding="utf-8") as fh:
                fh.write(dumped + "\n")
        except Exception as exc:
            print(json.dumps({"ok": False,
                              "error": "could not write %s: %s" % (args.output, exc)},
                             indent=2))
            return 2
        print(json.dumps({
            "ok": True, "output": os.path.abspath(args.output),
            "entry_count": index["entry_count"], "stub_count": index["stub_count"],
            "problem_count": len(index["problems"]),
        }, indent=2, ensure_ascii=False))
    else:
        print(dumped)
    return 0


if __name__ == "__main__":
    sys.exit(main())
